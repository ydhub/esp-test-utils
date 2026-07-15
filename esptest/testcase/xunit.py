import functools
import json
import logging
import os
import platform
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

import esptest.common.compat_typing as t
from esptest.common.timestamp import timestamp_iso

from .result import ResultDetail, TestCaseResult, TestCaseStatus, TestSuiteResult, TestSuitesResult

logger = logging.getLogger(__name__)

_MethodT = t.TypeVar('_MethodT', bound=t.Callable[..., t.Any])


def _synchronized(method: _MethodT) -> _MethodT:
    """Guard an XunitLogger method with the instance reentrant lock so concurrent
    callers (e.g. serial monitor threads calling add_sys_out) stay consistent."""

    @functools.wraps(method)
    def wrapper(self: 'XunitLogger', *args: t.Any, **kwargs: t.Any) -> t.Any:
        with self._lock:  # noqa: SLF001  # pylint: disable=protected-access
            return method(self, *args, **kwargs)

    return t.cast(_MethodT, wrapper)


XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>\n'
XUNIT_RESULT_FILE_NAME = 'XUNIT_RESULT.xml'
XUNIT_TEST_FRAMEWORK = 'esptest'
XUNIT_HOSTNAME = platform.node()
XUNIT_DEFAULT_TEST_SUITE = 'test-suite'
# xUnit timestamp requires ISO-like timezone format: %Y-%m-%dT%H:%M:%S%z.
TIMESTAMP_FORMATS = '%Y-%m-%dT%H:%M:%S%z'
DEFAULT_FAIL_MESSAGE = 'Fail Reason Not Set'
DEFAULT_FAIL_TYPE = 'unknown'
# Default per-case stdout/stderr budget: keep the first half (frozen head) and the
# most recent half (sliding tail); head/tail sizes are configurable on XunitLogger.
DEFAULT_STD_HEAD_LEN = 4 * 1024
DEFAULT_STD_TAIL_LEN = 4 * 1024
MAX_XUNIT_STD_LEN = DEFAULT_STD_HEAD_LEN + DEFAULT_STD_TAIL_LEN


def _is_xml_char(codepoint: int) -> bool:
    # Valid XML 1.0 characters: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
    return (
        codepoint in (0x09, 0x0A, 0x0D)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _xml_safe_text(value: str) -> str:
    """Replace characters that are invalid in XML 1.0 with a readable escape so the
    generated document stays well-formed and can be parsed back."""
    if all(_is_xml_char(ord(char)) for char in value):
        return value
    chars = []
    for char in value:
        codepoint = ord(char)
        if _is_xml_char(codepoint):
            chars.append(char)
        elif codepoint <= 0xFF:
            chars.append(f'\\x{codepoint:02x}')
        else:
            chars.append(f'\\u{codepoint:04x}')
    return ''.join(chars)


class _BoundedText:
    """Accumulate streaming text with a bounded footprint.

    The first ``head_limit`` characters are captured once and then frozen, while
    the most recent ``tail_limit`` characters are kept in a sliding ring buffer.
    Content in the middle is dropped. Appends are amortized ``O(len(text))`` and
    memory never exceeds ``head_limit + tail_limit`` characters.
    """

    def __init__(self, head_limit: int, tail_limit: int, initial: str = '') -> None:
        self.head_limit = max(int(head_limit), 0)
        self.tail_limit = max(int(tail_limit), 0)
        self._head_parts: t.List[str] = []
        self._head_len = 0
        self._tail: deque = deque()
        self._tail_len = 0
        self._dropped = False
        if initial:
            self.append(initial)

    @property
    def is_empty(self) -> bool:
        return self._head_len == 0 and self._tail_len == 0 and not self._dropped

    def append(self, text: str) -> None:
        if not text:
            return
        if self._head_len < self.head_limit:
            room = self.head_limit - self._head_len
            head_part = text[:room]
            if head_part:
                self._head_parts.append(head_part)
                self._head_len += len(head_part)
            text = text[room:]
            if not text:
                return
        if self.tail_limit <= 0:
            self._dropped = True
            return
        self._tail.append(text)
        self._tail_len += len(text)
        self._trim_tail()

    def _trim_tail(self) -> None:
        while self._tail_len > self.tail_limit and self._tail:
            overflow = self._tail_len - self.tail_limit
            first = self._tail[0]
            if len(first) <= overflow:
                self._tail.popleft()
                self._tail_len -= len(first)
            else:
                self._tail[0] = first[overflow:]
                self._tail_len -= overflow
            self._dropped = True

    def render(self) -> str:
        head = ''.join(self._head_parts)
        tail = ''.join(self._tail)
        if not self._dropped:
            return head + tail
        return f'{head}\n\n...(too long, middle dropped)\n\n{tail}'


def _trim_long_text(
    value: t.Optional[str],
    head_len: int = DEFAULT_STD_HEAD_LEN,
    tail_len: int = DEFAULT_STD_TAIL_LEN,
) -> t.Optional[str]:
    """Keep the first ``head_len`` and last ``tail_len`` characters, dropping the
    middle and inserting a marker when anything is removed. Reuses _BoundedText."""
    if value is None:
        return None
    return _BoundedText(head_len, tail_len, value).render()


def _format_time(value: float) -> str:
    return f'{value:.6f}'.rstrip('0').rstrip('.') or '0'


def _json_dumps(data: t.Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _add_properties(parent: ET.Element, properties: t.Dict[str, str]) -> None:
    if not properties:
        return
    properties_elem = ET.SubElement(parent, 'properties')
    for name in sorted(properties):
        ET.SubElement(properties_elem, 'property', {'name': name, 'value': _xml_safe_text(str(properties[name]))})


def _case_properties(test_case: TestCaseResult) -> t.Dict[str, str]:
    properties = dict(test_case.properties)
    if test_case.logs is not None:
        properties['logs'] = _json_dumps(test_case.logs)
    if test_case.result_detail_files:
        properties['result_detail_files'] = _json_dumps(test_case.result_detail_files)
    if test_case.started_at is not None:
        properties['started_at'] = test_case.started_at
    return properties


def _add_status_element(testcase_elem: ET.Element, test_case: TestCaseResult) -> None:
    if test_case.status == TestCaseStatus.FAILED:
        failure = ET.SubElement(testcase_elem, 'failure')
        if test_case.failure_type is not None:
            failure.set('type', _xml_safe_text(test_case.failure_type))
        if test_case.message is not None:
            message = _xml_safe_text(test_case.message)
            failure.set('message', message)
            failure.text = message
    elif test_case.status == TestCaseStatus.ERROR:
        error = ET.SubElement(testcase_elem, 'error')
        if test_case.failure_type is not None:
            error.set('type', _xml_safe_text(test_case.failure_type))
        if test_case.message is not None:
            message = _xml_safe_text(test_case.message)
            error.set('message', message)
            error.text = message
    elif test_case.status == TestCaseStatus.SKIPPED:
        skipped = ET.SubElement(testcase_elem, 'skipped')
        if test_case.message is not None:
            skipped.set('message', _xml_safe_text(test_case.message))


def _test_case_to_xml(test_case: TestCaseResult) -> ET.Element:
    attrs = {'name': test_case.name}
    if test_case.classname:
        attrs['classname'] = test_case.classname
    if test_case.duration is not None:
        attrs['time'] = _format_time(test_case.duration)

    testcase_elem = ET.Element('testcase', attrs)
    _add_properties(testcase_elem, _case_properties(test_case))
    _add_status_element(testcase_elem, test_case)
    if test_case.stdout is not None:
        ET.SubElement(testcase_elem, 'system-out').text = _xml_safe_text(test_case.stdout)
    if test_case.stderr is not None:
        ET.SubElement(testcase_elem, 'system-err').text = _xml_safe_text(test_case.stderr)
    return testcase_elem


def _test_suite_to_xml(test_suite: TestSuiteResult) -> ET.Element:
    attrs = {
        'name': test_suite.name,
        'tests': str(test_suite.tests),
        'failures': str(test_suite.failures),
        'errors': str(test_suite.errors),
        'skipped': str(test_suite.skipped),
        'time': _format_time(test_suite.time),
    }
    if test_suite.timestamp is not None:
        attrs['timestamp'] = test_suite.timestamp
    if test_suite.package is not None:
        attrs['package'] = test_suite.package
    if test_suite.hostname is not None:
        attrs['hostname'] = test_suite.hostname
    if test_suite.file is not None:
        attrs['file'] = test_suite.file

    testsuite_elem = ET.Element('testsuite', attrs)
    _add_properties(testsuite_elem, test_suite.properties)
    for test_case in test_suite.test_cases:
        testsuite_elem.append(_test_case_to_xml(test_case))
    return testsuite_elem


def _test_suites_to_xml(test_suites: TestSuitesResult) -> ET.Element:
    root = ET.Element(
        'testsuites',
        {
            'name': test_suites.name,
            'tests': str(test_suites.tests),
            'failures': str(test_suites.failures),
            'errors': str(test_suites.errors),
            'skipped': str(test_suites.skipped),
            'time': _format_time(test_suites.time),
        },
    )
    _add_properties(root, test_suites.properties)
    for test_suite in test_suites.test_suites:
        root.append(_test_suite_to_xml(test_suite))
    return root


def generate_xunit_xml(test_suites: TestSuitesResult) -> str:
    root = _test_suites_to_xml(test_suites)
    return XML_DECLARATION + ET.tostring(root, encoding='unicode')


def save_xunit_xml(test_suites: TestSuitesResult, path: t.Union[str, Path]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_xunit_xml(test_suites), encoding='utf-8')
    return target


def _parse_float(value: t.Optional[str]) -> t.Optional[float]:
    if not value:
        return None
    return float(value)


def _parse_properties(elem: ET.Element) -> t.Dict[str, str]:
    properties: t.Dict[str, str] = {}
    properties_elem = elem.find('properties')
    if properties_elem is None:
        return properties
    for prop in properties_elem.findall('property'):
        name = prop.get('name')
        if name is not None:
            properties[name] = prop.get('value', '')
    return properties


def _pop_json_property(properties: t.Dict[str, str], name: str) -> t.Optional[t.Any]:
    value = properties.pop(name, None)
    if value is None:
        return None
    return json.loads(value)


def _parse_case_status(testcase_elem: ET.Element) -> t.Tuple[str, t.Optional[str], t.Optional[str]]:
    failure = testcase_elem.find('failure')
    if failure is not None:
        return TestCaseStatus.FAILED, failure.get('message') or failure.text, failure.get('type')
    error = testcase_elem.find('error')
    if error is not None:
        return TestCaseStatus.ERROR, error.get('message') or error.text, error.get('type')
    skipped = testcase_elem.find('skipped')
    if skipped is not None:
        return TestCaseStatus.SKIPPED, skipped.get('message') or skipped.text, None
    return TestCaseStatus.PASSED, None, None


def _find_text(parent: ET.Element, tag: str) -> t.Optional[str]:
    elem = parent.find(tag)
    if elem is None:
        return None
    return elem.text


def _load_result_details(result_detail_files: t.List[str], base_dir: t.Optional[Path]) -> t.List[ResultDetail]:
    """Load referenced ``.json`` detail files (relative to ``base_dir``) into
    ResultDetail objects. Missing / unreadable / non-json files are skipped so a
    partially-available report still parses."""
    details: t.List[ResultDetail] = []
    if base_dir is None:
        return details
    for rel_path in result_detail_files:
        if not str(rel_path).lower().endswith('.json'):
            continue
        try:
            detail = ResultDetail.load_json(base_dir / rel_path)
        except (OSError, ValueError) as err:
            logger.warning('Failed to load result detail file %s: %s', rel_path, err)
            continue
        detail.file = rel_path
        details.append(detail)
    return details


def _parse_test_case(testcase_elem: ET.Element, base_dir: t.Optional[Path] = None) -> TestCaseResult:
    properties = _parse_properties(testcase_elem)
    result_detail_files = _pop_json_property(properties, 'result_detail_files') or []
    logs = _pop_json_property(properties, 'logs')
    started_at = properties.pop('started_at', None)
    status, message, failure_type = _parse_case_status(testcase_elem)
    return TestCaseResult(
        name=testcase_elem.get('name', ''),
        classname=testcase_elem.get('classname', ''),
        status=status,
        duration=_parse_float(testcase_elem.get('time')),
        message=message,
        failure_type=failure_type,
        stdout=_find_text(testcase_elem, 'system-out'),
        stderr=_find_text(testcase_elem, 'system-err'),
        properties=properties,
        logs=logs,
        result_detail_files=result_detail_files,
        result_details=_load_result_details(result_detail_files, base_dir),
        started_at=started_at,
    )


def _parse_test_suite(testsuite_elem: ET.Element, base_dir: t.Optional[Path] = None) -> TestSuiteResult:
    return TestSuiteResult(
        name=testsuite_elem.get('name', ''),
        test_cases=[_parse_test_case(elem, base_dir) for elem in testsuite_elem.findall('testcase')],
        properties=_parse_properties(testsuite_elem),
        timestamp=testsuite_elem.get('timestamp'),
        package=testsuite_elem.get('package'),
        hostname=testsuite_elem.get('hostname'),
        file=testsuite_elem.get('file'),
    )


def _load_root(xml_or_path: t.Union[str, Path]) -> ET.Element:
    if isinstance(xml_or_path, Path):
        return ET.parse(str(xml_or_path)).getroot()
    xml_text = str(xml_or_path)
    if xml_text.lstrip().startswith('<'):
        return ET.fromstring(xml_text)
    return ET.parse(xml_text).getroot()


def _resolve_base_dir(xml_or_path: t.Union[str, Path], base_dir: t.Optional[t.Union[str, Path]]) -> t.Optional[Path]:
    """Directory used to resolve relative result_detail_files. Falls back to the
    parent of the report file; returns None when parsing an in-memory XML string."""
    if base_dir is not None:
        return Path(base_dir)
    if isinstance(xml_or_path, Path):
        return xml_or_path.parent
    xml_text = str(xml_or_path)
    if xml_text.lstrip().startswith('<'):
        return None
    return Path(xml_text).parent


def parse_xunit_xml(
    xml_or_path: t.Union[str, Path],
    base_dir: t.Optional[t.Union[str, Path]] = None,
    load_result_details: bool = True,
) -> TestSuitesResult:
    root = _load_root(xml_or_path)
    resolved_base = _resolve_base_dir(xml_or_path, base_dir) if load_result_details else None
    if root.tag == 'testsuite':
        return TestSuitesResult(test_suites=[_parse_test_suite(root, resolved_base)])
    if root.tag != 'testsuites':
        raise ValueError(f'Unsupported xUnit root element: {root.tag}')

    return TestSuitesResult(
        name=root.get('name', 'testsuites'),
        test_suites=[_parse_test_suite(elem, resolved_base) for elem in root.findall('testsuite')],
        properties=_parse_properties(root),
    )


class XunitLogger:
    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        path: t.Union[str, Path],
        suite_name: str = XUNIT_DEFAULT_TEST_SUITE,
        file_name: str = XUNIT_RESULT_FILE_NAME,
        flush_interval: float = 2.0,
        timestamp: t.Optional[str] = None,
        package: str = XUNIT_TEST_FRAMEWORK,
        hostname: str = XUNIT_HOSTNAME,
        std_head_len: int = DEFAULT_STD_HEAD_LEN,
        std_tail_len: int = DEFAULT_STD_TAIL_LEN,
    ) -> None:
        base_path = Path(path)
        self._lock = threading.RLock()
        # Treat the path as a file only when it clearly points at an .xml file; a
        # directory (even one whose name contains a dot, e.g. "run.2026") gets the
        # default result file name appended.
        path_str = str(path)
        ends_with_sep = path_str.endswith('/') or (os.sep != '/' and path_str.endswith(os.sep))
        if base_path.suffix.lower() == '.xml' and not ends_with_sep and not base_path.is_dir():
            self.xunit_file = base_path
        else:
            self.xunit_file = base_path / file_name
        self.flush_interval = max(float(flush_interval), 0.0)
        self.std_head_len = max(int(std_head_len), 0)
        self.std_tail_len = max(int(std_tail_len), 0)
        self.test_suites = TestSuitesResult(
            test_suites=[
                TestSuiteResult(
                    name=suite_name,
                    timestamp=timestamp or time.strftime(TIMESTAMP_FORMATS),
                    package=package,
                    hostname=hostname,
                )
            ]
        )
        self.running_case: t.Optional[TestCaseResult] = None
        self._pre_case_cache = self._new_buffer()
        self._stdout = self._new_buffer()
        self._stderr = self._new_buffer()
        self._case_start_time: t.Optional[float] = None
        self._last_flush_time: t.Optional[float] = None

    def _new_buffer(self) -> _BoundedText:
        return _BoundedText(self.std_head_len, self.std_tail_len)

    @staticmethod
    def _rendered(buffer: _BoundedText) -> t.Optional[str]:
        return None if buffer.is_empty else buffer.render()

    @property
    def test_suite(self) -> TestSuiteResult:
        return self.test_suites.test_suites[0]

    @property
    def has_running_case(self) -> bool:
        return self.running_case is not None

    @property
    def current_test_case(self) -> t.Optional[TestCaseResult]:
        if self.running_case is not None:
            return self.running_case
        if self.test_suite.test_cases:
            return self.test_suite.test_cases[-1]
        return None

    @_synchronized
    def set_config(self, config: t.Dict[str, str]) -> None:
        if 'suite_name' in config:
            self.test_suite.name = config['suite_name']
        if 'package' in config:
            self.test_suite.package = config['package']
        if 'file' in config:
            self.test_suite.file = config['file']
        if 'hostname' in config:
            self.test_suite.hostname = config['hostname']

    @_synchronized
    def begin_case(self, case_id: str, classname: str = '', category: t.Optional[str] = None) -> None:
        if self.running_case is not None:
            self.close('Test Case Ended Unexpected!')
        properties = {}
        if category is not None:
            properties['category'] = category
        self.running_case = TestCaseResult(name=case_id, classname=classname or '', properties=properties)
        self._case_start_time = time.time()
        self.running_case.started_at = timestamp_iso()
        self._stdout = self._new_buffer()
        self._stderr = self._new_buffer()
        if not self._pre_case_cache.is_empty:
            self._stdout.append(f'->std logs before case start:\n{self._pre_case_cache.render()}\n')
        self._pre_case_cache = self._new_buffer()
        self.flush(force=True)

    @_synchronized
    def add_sys_out(self, message: str) -> None:
        self._add_output('stdout', message)
        self.flush()

    @_synchronized
    def add_sys_err(self, message: str) -> None:
        self._add_output('stderr', message)
        self.flush()

    def _add_output(self, field_name: str, message: str) -> None:
        if self.running_case is None:
            self._pre_case_cache.append(message)
            return
        buffer = self._stdout if field_name == 'stdout' else self._stderr
        buffer.append(message if buffer.is_empty else '\n' + message)

    @_synchronized
    def add_failure(self, message: str = DEFAULT_FAIL_MESSAGE, fail_type: str = DEFAULT_FAIL_TYPE) -> None:
        if self.running_case is None:
            raise RuntimeError('No running test case')
        self.running_case.status = TestCaseStatus.FAILED
        self.running_case.message = _trim_long_text(message) or DEFAULT_FAIL_MESSAGE
        self.running_case.failure_type = fail_type or DEFAULT_FAIL_TYPE
        self.flush(force=True)

    @_synchronized
    def add_error(self, message: str = DEFAULT_FAIL_MESSAGE) -> None:
        if self.running_case is None:
            raise RuntimeError('No running test case')
        self.running_case.status = TestCaseStatus.ERROR
        self.running_case.message = _trim_long_text(message) or DEFAULT_FAIL_MESSAGE
        self.flush(force=True)

    @_synchronized
    def add_skipped(self, message: str = '') -> None:
        if self.running_case is None:
            raise RuntimeError('No running test case')
        self.running_case.status = TestCaseStatus.SKIPPED
        self.running_case.message = message or None
        self.flush(force=True)

    @_synchronized
    def clear_failures(self) -> None:
        if self.running_case is None:
            raise RuntimeError('No running test case')
        self.running_case.status = TestCaseStatus.PASSED
        self.running_case.message = None
        self.flush(force=True)

    @_synchronized
    def end_case(self, result: bool = True, message: str = '', failure_type: str = '') -> Path:
        if self.running_case is None:
            raise RuntimeError('No running test case')
        if not result:
            self.add_failure(message or DEFAULT_FAIL_MESSAGE, failure_type or DEFAULT_FAIL_TYPE)
        if self._case_start_time is not None:
            self.running_case.duration = round(time.time() - self._case_start_time, 3)
        self.running_case.stdout = self._rendered(self._stdout)
        self.running_case.stderr = self._rendered(self._stderr)
        self.test_suite.test_cases.append(self.running_case)
        self.running_case = None
        self._case_start_time = None
        self._stdout = self._new_buffer()
        self._stderr = self._new_buffer()
        return self.flush(force=True)

    @_synchronized
    def flush(self, force: bool = False) -> Path:
        now = time.time()
        if not force and self._last_flush_time is not None and now - self._last_flush_time < self.flush_interval:
            return self.xunit_file
        self._last_flush_time = now
        return save_xunit_xml(self._snapshot_test_suites(), self.xunit_file)

    @_synchronized
    def close(self, message: str = 'Test case interrupted before end_case') -> Path:
        if self.running_case is not None:
            self.running_case.status = TestCaseStatus.ERROR
            self.running_case.message = message
            if self._case_start_time is not None:
                self.running_case.duration = round(time.time() - self._case_start_time, 3)
            self.running_case.stdout = self._rendered(self._stdout)
            self.running_case.stderr = self._rendered(self._stderr)
            self.test_suite.test_cases.append(self.running_case)
            self.running_case = None
            self._case_start_time = None
            self._stdout = self._new_buffer()
            self._stderr = self._new_buffer()
        return self.flush(force=True)

    def _snapshot_test_suites(self) -> TestSuitesResult:
        test_suites = []
        for suite in self.test_suites.test_suites:
            test_suites.append(
                TestSuiteResult(
                    name=suite.name,
                    test_cases=list(suite.test_cases),
                    properties=dict(suite.properties),
                    timestamp=suite.timestamp,
                    package=suite.package,
                    hostname=suite.hostname,
                    file=suite.file,
                )
            )
        if self.running_case is not None:
            test_suites[0].test_cases.append(self._running_case_snapshot())
        return TestSuitesResult(
            name=self.test_suites.name, test_suites=test_suites, properties=dict(self.test_suites.properties)
        )

    def _running_case_snapshot(self) -> TestCaseResult:
        assert self.running_case is not None
        status = self.running_case.status
        message = self.running_case.message
        if status == TestCaseStatus.PASSED:
            status = TestCaseStatus.ERROR
            message = 'Test case is still running'
        duration = None
        if self._case_start_time is not None:
            duration = round(time.time() - self._case_start_time, 3)
        properties = dict(self.running_case.properties)
        properties['running'] = 'true'
        return TestCaseResult(
            name=self.running_case.name,
            classname=self.running_case.classname,
            status=status,
            duration=duration,
            message=message,
            failure_type=self.running_case.failure_type,
            stdout=self._rendered(self._stdout),
            stderr=self._rendered(self._stderr),
            properties=properties,
            logs=self.running_case.logs,
            result_detail_files=list(self.running_case.result_detail_files),
            started_at=self.running_case.started_at,
        )

    @_synchronized
    def get_cur_case_result(self) -> t.Tuple[bool, str]:
        current = self.current_test_case
        if current is not None and current.status in (TestCaseStatus.FAILED, TestCaseStatus.ERROR):
            return False, current.message or ''
        return True, ''

    @_synchronized
    def get_cur_case_id(self) -> str:
        current = self.current_test_case
        return current.name if current is not None else ''
