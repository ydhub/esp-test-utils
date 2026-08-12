from pathlib import Path

import pytest

from esptest.common.timestamp import parse_timestamp
from esptest.testcase.result import TestCaseResult, TestCaseStatus, TestSuiteResult, TestSuitesResult
from esptest.testcase.xunit import (
    XUNIT_RESULT_FILE_NAME,
    XunitLogger,
    _trim_long_text,
    generate_xunit_xml,
    parse_xunit_xml,
    save_xunit_xml,
)


def test_generate_xunit_xml_writes_result_detail_files_property() -> None:
    suites = TestSuitesResult(
        name='esp-test-utils',
        test_suites=[
            TestSuiteResult(
                name='iperf',
                test_cases=[
                    TestCaseResult(
                        name='test_tcp_tx',
                        classname='iperf.tcp',
                        duration=60.0,
                        stdout='throughput ok',
                        properties={'target': 'esp32'},
                        result_detail_files=['result_details/test_tcp_tx.json'],
                    )
                ],
            )
        ],
    )

    xml_text = generate_xunit_xml(suites)

    assert '<testsuites' in xml_text
    assert 'name="esp-test-utils"' in xml_text
    assert 'tests="1"' in xml_text
    assert '<testsuite' in xml_text
    assert '<testcase' in xml_text
    assert 'classname="iperf.tcp"' in xml_text
    assert '<system-out>throughput ok</system-out>' in xml_text
    assert 'name="result_detail_files"' in xml_text
    assert 'result_details/test_tcp_tx.json' in xml_text
    assert 'name="performance"' not in xml_text


def test_parse_xunit_xml_returns_double_layer_result() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="root" tests="3" failures="1" errors="0" skipped="1" time="3.5">
  <testsuite name="wifi" tests="3" failures="1" errors="0" skipped="1" time="3.5">
    <testcase classname="wifi.station" name="test_connect" time="1.5">
      <properties>
        <property name="target" value="esp32" />
        <property name="result_detail_files" value="[&quot;result_details/test_connect.json&quot;]" />
      </properties>
      <system-out>connected</system-out>
    </testcase>
    <testcase classname="wifi.station" name="test_disconnect" time="2.0">
      <failure message="disconnect failed">traceback</failure>
      <system-err>stderr text</system-err>
    </testcase>
    <testcase classname="wifi.station" name="test_skip">
      <skipped message="not supported" />
    </testcase>
  </testsuite>
</testsuites>
"""

    suites = parse_xunit_xml(xml_text)

    assert isinstance(suites, TestSuitesResult)
    assert suites.name == 'root'
    assert len(suites.test_suites) == 1
    suite = suites.test_suites[0]
    assert isinstance(suite, TestSuiteResult)
    assert suite.name == 'wifi'
    assert suite.tests == 3
    assert [case.name for case in suite.test_cases] == ['test_connect', 'test_disconnect', 'test_skip']
    assert suite.test_cases[0].status == TestCaseStatus.PASSED
    assert suite.test_cases[0].stdout == 'connected'
    assert suite.test_cases[0].properties == {'target': 'esp32'}
    assert suite.test_cases[0].result_detail_files == ['result_details/test_connect.json']
    assert suite.test_cases[1].status == TestCaseStatus.FAILED
    assert suite.test_cases[1].message == 'disconnect failed'
    assert suite.test_cases[1].stderr == 'stderr text'
    assert suite.test_cases[2].status == TestCaseStatus.SKIPPED
    assert suite.test_cases[2].message == 'not supported'


def test_save_and_parse_xunit_xml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / 'xunit.xml'
    original = TestSuitesResult(
        test_suites=[
            TestSuiteResult(
                name='suite-a',
                test_cases=[
                    TestCaseResult(
                        name='passed_case',
                        properties={'chip': 'esp32'},
                        result_detail_files=['details/passed_case.json'],
                    ),
                    TestCaseResult(name='error_case', status=TestCaseStatus.ERROR, message='boom', stderr='stack'),
                ],
            )
        ]
    )

    saved_path = save_xunit_xml(original, path)
    parsed = parse_xunit_xml(saved_path)

    assert saved_path == path
    assert parsed.tests == 2
    assert parsed.errors == 1
    assert parsed.test_suites[0].name == 'suite-a'
    assert parsed.test_suites[0].test_cases[0].properties == {'chip': 'esp32'}
    assert parsed.test_suites[0].test_cases[0].result_detail_files == ['details/passed_case.json']
    assert parsed.test_suites[0].test_cases[1].status == TestCaseStatus.ERROR
    assert parsed.test_suites[0].test_cases[1].message == 'boom'


def test_xunit_logger_saves_xml_after_each_case(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path, suite_name='wifi-suite')
    logger.set_config({'package': 'esp-test-utils', 'file': 'test_wifi.py'})

    logger.begin_case('test_connect', classname='wifi.station')
    logger.add_sys_out('connected')
    first_path = logger.end_case()

    assert first_path == tmp_path / XUNIT_RESULT_FILE_NAME
    parsed = parse_xunit_xml(first_path)
    suite = parsed.test_suites[0]
    assert suite.name == 'wifi-suite'
    assert suite.package == 'esp-test-utils'
    assert suite.file == 'test_wifi.py'
    assert suite.tests == 1
    assert suite.test_cases[0].name == 'test_connect'
    assert suite.test_cases[0].status == TestCaseStatus.PASSED
    assert suite.test_cases[0].stdout == 'connected'

    logger.begin_case('test_disconnect', classname='wifi.station')
    logger.add_sys_err('serial closed')
    second_path = logger.end_case(result=False, message='disconnect failed')

    assert second_path == first_path
    parsed = parse_xunit_xml(second_path)
    suite = parsed.test_suites[0]
    assert suite.tests == 2
    assert suite.failures == 1
    assert suite.test_cases[1].status == TestCaseStatus.FAILED
    assert suite.test_cases[1].message == 'disconnect failed'
    assert suite.test_cases[1].stderr == 'serial closed'


def test_xunit_logger_accepts_suite_metadata_from_init(tmp_path: Path) -> None:
    logger = XunitLogger(
        tmp_path,
        suite_name='custom-suite',
        timestamp='2026-07-07T10:00:00+0000',
        package='custom-package',
        hostname='custom-host',
    )

    logger.begin_case('test_metadata')
    logger.end_case()

    suite = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME).test_suites[0]
    assert suite.name == 'custom-suite'
    assert suite.timestamp == '2026-07-07T10:00:00+0000'
    assert suite.package == 'custom-package'
    assert suite.hostname == 'custom-host'


def test_set_config_stores_unknown_keys_as_suite_properties(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path, suite_name='wifi-suite')
    logger.set_config(
        {
            'suite_name': 'renamed-suite',
            'package': 'esp-test-utils',
            'file': 'test_wifi.py',
            'hostname': 'ci-host',
            'target': 'esp32',
            'idf_version': '5.3',
        }
    )

    logger.begin_case('test_connect')
    logger.end_case()

    suite = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME).test_suites[0]
    assert suite.name == 'renamed-suite'
    assert suite.package == 'esp-test-utils'
    assert suite.file == 'test_wifi.py'
    assert suite.hostname == 'ci-host'
    assert suite.properties == {'target': 'esp32', 'idf_version': '5.3'}


def test_set_default_config_merges_on_init_and_persists(tmp_path: Path) -> None:
    saved = XunitLogger.get_default_config()
    try:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config({'package': 'default-pkg', 'file': 'default_file.py', 'target': 'esp32'})
        assert XunitLogger.get_default_config() == {
            'package': 'default-pkg',
            'file': 'default_file.py',
            'target': 'esp32',
        }

        first = XunitLogger(tmp_path / 'first', suite_name='suite-a')
        assert first.get_config()['package'] == 'default-pkg'
        assert first.get_config()['file'] == 'default_file.py'
        assert first.get_config()['target'] == 'esp32'
        assert first.get_config()['suite_name'] == 'suite-a'

        # default config is not consumed; a second instance still gets it
        second = XunitLogger(tmp_path / 'second', suite_name='suite-b')
        assert second.test_suite.package == 'default-pkg'
        assert second.test_suite.properties['target'] == 'esp32'

        first.set_config({'hostname': 'host-1', 'board': 'devkit'})
        cfg = first.get_config()
        assert cfg['hostname'] == 'host-1'
        assert cfg['board'] == 'devkit'
        assert cfg['target'] == 'esp32'
    finally:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config(saved)


def test_get_default_config_returns_a_copy() -> None:
    saved = XunitLogger.get_default_config()
    try:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config({'target': 'esp32'})
        cfg = XunitLogger.get_default_config()
        cfg['target'] = 'mutated'
        cfg['extra'] = 'leak'
        assert XunitLogger.get_default_config() == {'target': 'esp32'}
    finally:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config(saved)


def test_clear_default_config_resets_process_defaults(tmp_path: Path) -> None:
    saved = XunitLogger.get_default_config()
    try:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config({'package': 'default-pkg', 'target': 'esp32'})
        XunitLogger.clear_default_config()
        assert XunitLogger.get_default_config() == {}

        logger = XunitLogger(tmp_path)
        assert 'target' not in logger.get_config()
        assert logger.test_suite.package != 'default-pkg'
    finally:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config(saved)


def test_constructor_args_override_default_config(tmp_path: Path) -> None:
    saved = XunitLogger.get_default_config()
    try:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config(
            {
                'suite_name': 'default-suite',
                'package': 'default-pkg',
                'hostname': 'default-host',
                'file': 'default_file.py',
                'target': 'esp32',
            }
        )
        logger = XunitLogger(
            tmp_path,
            suite_name='explicit-suite',
            package='explicit-pkg',
            hostname='explicit-host',
        )
        cfg = logger.get_config()
        assert cfg['suite_name'] == 'explicit-suite'
        assert cfg['package'] == 'explicit-pkg'
        assert cfg['hostname'] == 'explicit-host'
        assert cfg['file'] == 'default_file.py'
        assert cfg['target'] == 'esp32'
    finally:
        XunitLogger.clear_default_config()
        XunitLogger.set_default_config(saved)


def test_set_case_properties_merges_without_immediate_flush(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)
    logger.begin_case('test_connect', category='wifi')

    logger.set_case_properties({'target': 'esp32', 'config': 'debug'})
    logger.set_case_properties({'config': 'release'})

    before_end = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME)
    assert 'target' not in before_end.test_suites[0].test_cases[0].properties

    report_path = logger.end_case()
    case = parse_xunit_xml(report_path).test_suites[0].test_cases[0]
    assert case.properties == {
        'category': 'wifi',
        'target': 'esp32',
        'config': 'release',
    }


def test_set_case_properties_requires_running_case(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    with pytest.raises(RuntimeError, match='No running test case'):
        logger.set_case_properties({'target': 'esp32'})


def test_set_case_properties_rejects_reserved_running_key(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)
    logger.begin_case('test_connect')

    with pytest.raises(ValueError, match=r"property 'running' is reserved"):
        logger.set_case_properties({'running': 'true'})
    with pytest.raises(ValueError, match=r"property 'running' is reserved"):
        logger.set_case_properties({'target': 'esp32', 'running': 'false'})

    logger.set_case_properties({'target': 'esp32'})
    logger.end_case()
    case = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME).test_suites[0].test_cases[0]
    assert case.properties == {'target': 'esp32'}
    assert 'running' not in case.properties


def test_add_case_detail_auto_generates_incrementing_file_names(tmp_path: Path) -> None:
    from esptest.testcase.result import ResultDetail

    logger = XunitLogger(tmp_path)

    logger.begin_case('test_tcp_tx')
    first = logger.add_case_detail(ResultDetail(type='throughput', result={'mbps': 94.2}))
    second = logger.add_case_detail(ResultDetail(type='throughput', result={'mbps': 95.0}))
    assert first.file == 'case_details/1.json'
    assert second.file == 'case_details/2.json'
    assert (tmp_path / 'case_details/1.json').is_file()
    assert (tmp_path / 'case_details/2.json').is_file()
    logger.end_case()

    # the counter is not reset per case, so a new case keeps incrementing
    logger.begin_case('test_tcp_rx')
    third = logger.add_case_detail(ResultDetail(type='throughput', result={'mbps': 90.0}))
    assert third.file == 'case_details/3.json'
    saved_path = logger.end_case()

    cases = parse_xunit_xml(saved_path).test_suites[0].test_cases
    assert cases[0].result_detail_files == ['case_details/1.json', 'case_details/2.json']
    assert [detail.result['mbps'] for detail in cases[0].result_details] == [94.2, 95.0]
    assert cases[1].result_detail_files == ['case_details/3.json']
    assert cases[1].result_details[0].result['mbps'] == 90.0


def test_add_case_detail_uses_explicit_file_name(tmp_path: Path) -> None:
    from esptest.testcase.result import ResultDetail

    logger = XunitLogger(tmp_path)

    logger.begin_case('test_tcp_tx')
    detail = logger.add_case_detail(
        ResultDetail(type='throughput', result={'mbps': 94.2}, file='custom/detail.json'),
    )
    assert detail.file == 'custom/detail.json'
    assert (tmp_path / 'custom/detail.json').is_file()
    saved_path = logger.end_case()

    case = parse_xunit_xml(saved_path).test_suites[0].test_cases[0]
    assert case.result_detail_files == ['custom/detail.json']
    assert case.result_details[0].result == {'mbps': 94.2}


def test_add_case_detail_requires_running_case(tmp_path: Path) -> None:
    from esptest.testcase.result import ResultDetail

    logger = XunitLogger(tmp_path)

    with pytest.raises(RuntimeError, match='No running test case'):
        logger.add_case_detail(ResultDetail(type='throughput'))


def test_add_case_detail_rejects_reused_instance(tmp_path: Path) -> None:
    # calling add_case_detail() twice with the same mutable ResultDetail must
    # not silently overwrite the file already saved for it, or duplicate the
    # entry in result_details / result_detail_files.
    from esptest.testcase.result import ResultDetail

    logger = XunitLogger(tmp_path)

    logger.begin_case('test_tcp_tx')
    detail = ResultDetail(type='throughput', result={'mbps': 94.2})
    logger.add_case_detail(detail)

    with pytest.raises(ValueError, match='already added'):
        logger.add_case_detail(detail)

    assert logger.running_case is not None
    assert logger.running_case.result_detail_files == ['case_details/1.json']
    assert len(logger.running_case.result_details) == 1


def test_add_case_detail_does_not_register_when_save_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # if writing the JSON file fails, the case/report must not end up
    # referencing a detail file that was never actually written.
    from esptest.testcase.result import ResultDetail

    logger = XunitLogger(tmp_path)
    logger.begin_case('test_tcp_tx')
    detail = ResultDetail(type='throughput', result={'mbps': 94.2})

    def _boom(self: ResultDetail, path: object, indent: object = 2) -> Path:
        raise OSError('disk full')

    monkeypatch.setattr(ResultDetail, 'save_json', _boom)

    with pytest.raises(OSError, match='disk full'):
        logger.add_case_detail(detail)

    assert logger.running_case is not None
    assert logger.running_case.result_detail_files == []
    assert logger.running_case.result_details == []


def test_begin_case_records_started_at(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.begin_case('test_started_at')
    assert logger.running_case is not None
    assert logger.running_case.started_at
    logger.end_case()

    report_path = tmp_path / XUNIT_RESULT_FILE_NAME
    xml_text = report_path.read_text(encoding='utf-8')
    # started_at is emitted as <testcase timestamp="...">, not a property.
    assert 'timestamp="' in xml_text
    assert 'name="started_at"' not in xml_text

    case = parse_xunit_xml(report_path).test_suites[0].test_cases[0]
    assert case.started_at
    # started_at must be a parseable ISO timestamp
    parse_timestamp(case.started_at)
    assert 'started_at' not in case.properties


def test_generate_xunit_xml_writes_started_at_as_testcase_timestamp() -> None:
    suites = TestSuitesResult(
        test_suites=[
            TestSuiteResult(
                name='wifi',
                test_cases=[
                    TestCaseResult(
                        name='test_connect',
                        duration=1.5,
                        started_at='2026-08-04T11:30:25+0800',
                        properties={'target': 'esp32'},
                    )
                ],
            )
        ]
    )

    xml_text = generate_xunit_xml(suites)
    assert 'timestamp="2026-08-04T11:30:25+0800"' in xml_text
    assert 'name="started_at"' not in xml_text


def test_parse_xunit_xml_prefers_testcase_timestamp_over_property_started_at() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="root" tests="2" failures="0" errors="0" skipped="0" time="3">
  <testsuite name="wifi" tests="2" failures="0" errors="0" skipped="0" time="3">
    <testcase name="from_attr" time="1" timestamp="2026-08-04T11:30:25+0800">
      <properties>
        <property name="started_at" value="2026-01-01T00:00:00+0800" />
      </properties>
    </testcase>
    <testcase name="from_property" time="2">
      <properties>
        <property name="started_at" value="2026-07-01T10:00:00+0800" />
      </properties>
    </testcase>
  </testsuite>
</testsuites>
"""

    suites = parse_xunit_xml(xml_text)
    cases = suites.test_suites[0].test_cases
    assert cases[0].started_at == '2026-08-04T11:30:25+0800'
    assert 'started_at' not in cases[0].properties
    assert cases[1].started_at == '2026-07-01T10:00:00+0800'
    assert 'started_at' not in cases[1].properties


def test_xunit_logger_carries_stdout_before_case_start(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.add_sys_out('boot log')
    logger.begin_case('test_boot')
    logger.end_case()

    parsed = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME)
    stdout = parsed.test_suites[0].test_cases[0].stdout
    assert stdout is not None
    assert 'std logs before case start' in stdout
    assert 'boot log' in stdout


def test_xunit_logger_persists_running_case_as_running(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.begin_case('test_crash_safe', classname='wifi.station')

    # Mid-run readers keep RUNNING; final-report default maps it to ERROR.
    live = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME, keep_running=True)
    assert live.test_suites[0].errors == 0
    assert live.test_suites[0].test_cases[0].status == TestCaseStatus.RUNNING
    assert live.test_suites[0].test_cases[0].message == 'Test case is still running'
    assert live.test_suites[0].test_cases[0].properties['running'] == 'true'

    final = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME)
    assert final.test_suites[0].errors == 1
    assert final.test_suites[0].test_cases[0].status == TestCaseStatus.ERROR
    assert final.test_suites[0].test_cases[0].message == 'Test case is still running'
    assert final.test_suites[0].test_cases[0].properties['running'] == 'true'


def test_parse_xunit_xml_maps_running_property_with_keep_running_flag() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="root" tests="2" failures="0" errors="0" skipped="0" time="1">
  <testsuite name="wifi" tests="2" failures="0" errors="0" skipped="0" time="1">
    <testcase name="still_going" time="1">
      <properties>
        <property name="running" value="true" />
      </properties>
    </testcase>
    <testcase name="failed_while_running" time="0">
      <properties>
        <property name="running" value="true" />
      </properties>
      <failure message="assert failed">assert failed</failure>
    </testcase>
  </testsuite>
</testsuites>
"""

    keep = parse_xunit_xml(xml_text, keep_running=True).test_suites[0].test_cases
    assert keep[0].status == TestCaseStatus.RUNNING
    assert keep[0].properties.get('running') == 'true'
    assert keep[1].status == TestCaseStatus.FAILED

    as_error = parse_xunit_xml(xml_text).test_suites[0].test_cases
    assert as_error[0].status == TestCaseStatus.ERROR
    assert as_error[0].message == 'Test case is still running'
    assert as_error[0].properties.get('running') == 'true'
    assert as_error[1].status == TestCaseStatus.FAILED


def test_parse_xunit_xml_maps_legacy_running_error_with_keep_running_flag() -> None:
    """Old flushes wrote <error>Test case is still running</error> + running=true."""
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="root" tests="1" failures="0" errors="1" skipped="0" time="1">
  <testsuite name="wifi" tests="1" failures="0" errors="1" skipped="0" time="1">
    <testcase name="legacy_running" time="1">
      <properties>
        <property name="running" value="true" />
      </properties>
      <error message="Test case is still running">Test case is still running</error>
    </testcase>
  </testsuite>
</testsuites>
"""

    keep = parse_xunit_xml(xml_text, keep_running=True).test_suites[0].test_cases[0]
    assert keep.status == TestCaseStatus.RUNNING
    assert keep.message == 'Test case is still running'

    # Default keeps the terminal ERROR for final-report consumers.
    final = parse_xunit_xml(xml_text).test_suites[0].test_cases[0]
    assert final.status == TestCaseStatus.ERROR
    assert final.message == 'Test case is still running'
    assert final.properties.get('running') == 'true'


def test_generate_and_parse_xunit_xml_round_trips_running_status() -> None:
    suites = TestSuitesResult(
        test_suites=[
            TestSuiteResult(
                name='wifi',
                test_cases=[
                    TestCaseResult(
                        name='in_progress',
                        status=TestCaseStatus.RUNNING,
                        message='Test case is still running',
                        properties={'running': 'true'},
                    )
                ],
            )
        ]
    )

    xml_text = generate_xunit_xml(suites)
    assert 'name="running"' in xml_text
    assert '<failure' not in xml_text
    assert '<error' not in xml_text

    keep = parse_xunit_xml(xml_text, keep_running=True)
    case = keep.test_suites[0].test_cases[0]
    assert case.status == TestCaseStatus.RUNNING
    assert case.properties.get('running') == 'true'
    assert keep.test_suites[0].errors == 0

    final = parse_xunit_xml(xml_text)
    assert final.test_suites[0].test_cases[0].status == TestCaseStatus.ERROR
    assert final.test_suites[0].errors == 1


def test_generate_xunit_xml_forces_running_property_true_for_running_status() -> None:
    """Status RUNNING must always emit running=true, even if the caller set false."""
    suites = TestSuitesResult(
        test_suites=[
            TestSuiteResult(
                name='wifi',
                test_cases=[
                    TestCaseResult(
                        name='in_progress',
                        status=TestCaseStatus.RUNNING,
                        message='Test case is still running',
                        properties={'running': 'false'},
                    )
                ],
            )
        ]
    )

    xml_text = generate_xunit_xml(suites)
    assert 'name="running" value="true"' in xml_text
    assert 'value="false"' not in xml_text

    keep = parse_xunit_xml(xml_text, keep_running=True).test_suites[0].test_cases[0]
    assert keep.status == TestCaseStatus.RUNNING
    assert keep.properties.get('running') == 'true'

    final = parse_xunit_xml(xml_text).test_suites[0].test_cases[0]
    assert final.status == TestCaseStatus.ERROR
    assert final.properties.get('running') == 'true'


def test_xunit_logger_throttles_stdout_flushes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr('time.time', lambda: now[0])
    logger = XunitLogger(tmp_path, flush_interval=2.0)

    logger.begin_case('test_streaming_logs')
    logger.add_sys_out('first log')
    parsed = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME)
    assert parsed.test_suites[0].test_cases[0].stdout is None

    now[0] = 101.9
    logger.add_sys_out('second log')
    parsed = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME)
    assert parsed.test_suites[0].test_cases[0].stdout is None

    now[0] = 102.0
    logger.add_sys_out('third log')
    parsed = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME)
    assert parsed.test_suites[0].test_cases[0].stdout == 'first log\nsecond log\nthird log'


def test_xunit_logger_failure_flushes_immediately(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr('time.time', lambda: now[0])
    logger = XunitLogger(tmp_path, flush_interval=60.0)

    logger.begin_case('test_fail_fast')
    logger.add_sys_out('before failure')
    logger.add_failure('assert failed')

    parsed = parse_xunit_xml(tmp_path / XUNIT_RESULT_FILE_NAME)
    case = parsed.test_suites[0].test_cases[0]
    assert case.status == TestCaseStatus.FAILED
    assert case.message == 'assert failed'
    assert case.stdout == 'before failure'


def test_xunit_logger_close_marks_running_case_interrupted(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.begin_case('test_interrupted')
    logger.add_sys_err('last stderr')
    saved_path = logger.close()

    parsed = parse_xunit_xml(saved_path)
    case = parsed.test_suites[0].test_cases[0]
    assert case.status == TestCaseStatus.ERROR
    assert case.message == 'Test case interrupted before end_case'
    assert case.stderr == 'last stderr'
    assert logger.has_running_case is False


def test_parse_xunit_xml_auto_loads_result_details(tmp_path: Path) -> None:
    from esptest.testcase.result import ResultDetail

    detail_rel = 'result_details/test_tcp_tx.json'
    detail = ResultDetail(type='throughput', result={'throughput_mbps': 94.2})
    detail.save_json(tmp_path / detail_rel)

    logger = XunitLogger(tmp_path)
    logger.begin_case('test_tcp_tx', classname='iperf.tcp')
    assert logger.running_case is not None
    logger.running_case.add_result_detail(detail, file_name=detail_rel)
    saved_path = logger.end_case()

    case = parse_xunit_xml(saved_path).test_suites[0].test_cases[0]
    assert case.result_detail_files == [detail_rel]
    assert len(case.result_details) == 1
    assert case.result_details[0].type == 'throughput'
    assert case.result_details[0].result == {'throughput_mbps': 94.2}
    assert case.result_details[0].file == detail_rel


def test_parse_xunit_xml_skips_result_details_for_xml_string() -> None:
    # parsing an in-memory string has no base dir, so files cannot be resolved
    xml_text = (
        '<testsuites name="root" tests="1" failures="0" errors="0" skipped="0" time="0">'
        '<testsuite name="iperf" tests="1" failures="0" errors="0" skipped="0" time="0">'
        '<testcase name="test_tcp_tx"><properties>'
        '<property name="result_detail_files" value="[&quot;result_details/x.json&quot;]" />'
        '</properties></testcase></testsuite></testsuites>'
    )

    case = parse_xunit_xml(xml_text).test_suites[0].test_cases[0]
    assert case.result_detail_files == ['result_details/x.json']
    assert case.result_details == []


def test_parse_xunit_xml_can_disable_result_detail_loading(tmp_path: Path) -> None:
    from esptest.testcase.result import ResultDetail

    detail_rel = 'result_details/test_tcp_tx.json'
    ResultDetail(type='throughput', result={'throughput_mbps': 94.2}).save_json(tmp_path / detail_rel)

    logger = XunitLogger(tmp_path)
    logger.begin_case('test_tcp_tx')
    assert logger.running_case is not None
    logger.running_case.result_detail_files.append(detail_rel)
    saved_path = logger.end_case()

    case = parse_xunit_xml(saved_path, load_result_details=False).test_suites[0].test_cases[0]
    assert case.result_detail_files == [detail_rel]
    assert case.result_details == []


def test_generate_xunit_xml_sanitizes_invalid_control_characters() -> None:
    # ANSI escape, NUL, bell, form-feed and vertical tab are common in serial logs
    # but are invalid in XML 1.0; they must not break serialize/parse round trips.
    raw = 'red\x1b[31mtext\x00bell\x07\x0cform\x0bvtab'
    suites = TestSuitesResult(
        test_suites=[
            TestSuiteResult(
                name='serial',
                test_cases=[
                    TestCaseResult(
                        name='test_ansi_log',
                        status=TestCaseStatus.FAILED,
                        message='boom\x1b[0m',
                        stdout=raw,
                        stderr=raw,
                        properties={'note': 'ctrl\x00char'},
                    )
                ],
            )
        ]
    )

    parsed = parse_xunit_xml(generate_xunit_xml(suites))

    case = parsed.test_suites[0].test_cases[0]
    expected = 'red\\x1b[31mtext\\x00bell\\x07\\x0cform\\x0bvtab'
    assert case.stdout == expected
    assert case.stderr == expected
    assert case.message == 'boom\\x1b[0m'
    assert case.properties['note'] == 'ctrl\\x00char'


def test_xunit_logger_sanitizes_control_characters_in_output(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.begin_case('test_ansi_stream')
    logger.add_sys_out('boot\x0cform-feed\x0bvtab\x1b[32mok')
    saved_path = logger.end_case()

    parsed = parse_xunit_xml(saved_path)
    case = parsed.test_suites[0].test_cases[0]
    assert case.stdout == 'boot\\x0cform-feed\\x0bvtab\\x1b[32mok'


def test_xunit_logger_bounds_output_with_frozen_head_and_sliding_tail(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path, std_head_len=10, std_tail_len=10, flush_interval=0)

    logger.begin_case('test_long_stream')
    for index in range(1, 50):
        logger.add_sys_out('line{:02d}'.format(index))
    saved_path = logger.end_case()

    case = parse_xunit_xml(saved_path).test_suites[0].test_cases[0]
    # frozen head keeps the earliest output, sliding tail keeps the most recent
    stdout = case.stdout
    assert stdout is not None
    assert 'line01' in stdout
    assert stdout.rstrip().endswith('line49')
    assert 'too long' in stdout.lower()
    # in-memory footprint never exceeds head_len + tail_len
    assert logger.std_head_len == 10 and logger.std_tail_len == 10


def test_xunit_logger_treats_dotted_directory_name_as_directory(tmp_path: Path) -> None:
    # a directory whose name contains a dot must not be mistaken for a result file
    log_dir = tmp_path / 'run.2026'
    logger = XunitLogger(log_dir)

    assert logger.xunit_file == log_dir / XUNIT_RESULT_FILE_NAME

    logger.begin_case('test_case')
    saved_path = logger.end_case()
    assert saved_path == log_dir / XUNIT_RESULT_FILE_NAME
    assert saved_path.is_file()


def test_xunit_logger_uses_explicit_xml_path_as_file(tmp_path: Path) -> None:
    xml_path = tmp_path / 'nested' / 'custom_result.xml'
    logger = XunitLogger(xml_path)

    assert logger.xunit_file == xml_path

    logger.begin_case('test_case')
    saved_path = logger.end_case()
    assert saved_path == xml_path
    assert saved_path.is_file()


def test_xunit_logger_add_failure_records_fail_type(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.begin_case('test_typed_failure')
    logger.add_failure('throughput too low', fail_type='performance')
    saved_path = logger.end_case()

    case = parse_xunit_xml(saved_path).test_suites[0].test_cases[0]
    assert case.status == TestCaseStatus.FAILED
    assert case.message == 'throughput too low'
    assert case.failure_type == 'performance'


def test_xunit_logger_add_failure_defaults_fail_type_to_unknown(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.begin_case('test_default_type')
    logger.add_failure('boom')
    saved_path = logger.end_case()

    case = parse_xunit_xml(saved_path).test_suites[0].test_cases[0]
    assert case.failure_type == 'unknown'


def test_generate_and_parse_xunit_xml_round_trips_failure_type() -> None:
    suites = TestSuitesResult(
        test_suites=[
            TestSuiteResult(
                name='wifi',
                test_cases=[
                    TestCaseResult(
                        name='test_connect',
                        status=TestCaseStatus.FAILED,
                        message='timeout',
                        failure_type='timeout_error',
                    )
                ],
            )
        ]
    )

    xml_text = generate_xunit_xml(suites)
    assert 'type="timeout_error"' in xml_text

    parsed = parse_xunit_xml(xml_text)
    case = parsed.test_suites[0].test_cases[0]
    assert case.failure_type == 'timeout_error'


def test_xunit_logger_get_cur_case_result_reflects_error_and_failure(tmp_path: Path) -> None:
    logger = XunitLogger(tmp_path)

    logger.begin_case('test_error')
    logger.add_error('crashed')
    assert logger.get_cur_case_result() == (False, 'crashed')
    logger.end_case()

    logger.begin_case('test_failure')
    logger.add_failure('assert failed')
    assert logger.get_cur_case_result() == (False, 'assert failed')
    logger.end_case()

    logger.begin_case('test_skip')
    logger.add_skipped('not supported')
    assert logger.get_cur_case_result() == (True, '')
    logger.end_case()

    logger.begin_case('test_pass')
    assert logger.get_cur_case_result() == (True, '')
    logger.end_case()


def test_trim_long_text_returns_none_and_short_text_unchanged() -> None:
    assert _trim_long_text(None) is None
    assert _trim_long_text('') == ''
    # a value up to head_len + tail_len is kept verbatim (no marker)
    assert _trim_long_text('abcdef', 3, 3) == 'abcdef'


def test_trim_long_text_keeps_head_and_tail_with_marker() -> None:
    trimmed = _trim_long_text('abcdefg', head_len=3, tail_len=3)

    assert trimmed == 'abc\n\n...(too long, middle dropped)\n\nefg'


def test_trim_long_text_supports_head_len_zero() -> None:
    # head_len=0 turns it into a pure tail (ring buffer) that keeps the most recent
    trimmed = _trim_long_text('abcdefghij', head_len=0, tail_len=4)

    assert trimmed == '\n\n...(too long, middle dropped)\n\nghij'


def test_trim_long_text_supports_tail_len_zero() -> None:
    # tail_len=0 keeps only the head; the -0 slicing pitfall must not leak the whole value
    trimmed = _trim_long_text('abcdefghij', head_len=4, tail_len=0)

    assert trimmed == 'abcd\n\n...(too long, middle dropped)\n\n'
