import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import esptest.common.compat_typing as t


@dataclass
class ResultDetail:
    """
    ResultDetail is a class that records the result of a performance test.

    Each accumulated record corresponds to one ``TestResultDetail`` database row
    and can be dumped as JSON / JSONL for batch import into the database.

    Database schema (``TestResultDetail``) that records the target::

        params:        dict[str, Any]           (JSONB, required)
        result:        dict[str, Any]           (JSONB, required)
        duration:      int | None
        logs:          list[dict[str, Any]] | None
        brief_message: str | None
        started_at:    datetime | None
        finished_at:   datetime | None
    """

    __test__ = False

    type: str
    context: str = ''
    params: t.Dict[str, Any] = field(default_factory=dict)
    result: t.Dict[str, Any] = field(default_factory=dict)
    brief_message: str = ''
    started_at: t.Optional[str] = None
    finished_at: t.Optional[str] = None
    # Relative path (to the report/log directory) of the file this detail was saved
    # to. Kept out of ``to_dict`` because it is location metadata, not DB content.
    file: str = ''

    def to_dict(self) -> t.Dict[str, Any]:
        return {
            'type': self.type,
            'context': self.context,
            'params': self.params,
            'result': self.result,
            'brief_message': self.brief_message,
            'started_at': self.started_at,
            'finished_at': self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: t.Dict[str, Any]) -> 'ResultDetail':
        return cls(
            type=data['type'],
            context=data.get('context', ''),
            params=dict(data.get('params') or {}),
            result=dict(data.get('result') or {}),
            brief_message=data.get('brief_message', ''),
            started_at=data.get('started_at'),
            finished_at=data.get('finished_at'),
        )

    @classmethod
    def load_json(cls, path: t.Union[str, Path]) -> 'ResultDetail':
        with open(path, encoding='utf-8') as f:
            return cls.from_dict(json.load(f))

    def to_json(self, indent: t.Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_text(self) -> str:
        lines = [
            f'Type: {self.type}',
            f'Context: {self.context}',
            f'Brief Message: {self.brief_message}',
        ]
        if self.started_at:
            lines.append(f'Started At: {self.started_at}')
        if self.finished_at:
            lines.append(f'Finished At: {self.finished_at}')
        lines.extend(
            [
                '',
                'Params:',
                json.dumps(self.params, ensure_ascii=False, indent=2, sort_keys=True),
                '',
                'Result:',
                json.dumps(self.result, ensure_ascii=False, indent=2, sort_keys=True),
            ]
        )
        return '\n'.join(lines)

    def to_markdown(self) -> str:
        sections = [
            f'# {self.type}',
            '',
            '## Context',
            self.context or '',
            '',
            '## Brief Message',
            self.brief_message or '',
        ]
        if self.started_at or self.finished_at:
            sections.extend(
                [
                    '',
                    '## Timestamps',
                    f'- Started At: {self.started_at or ""}',
                    f'- Finished At: {self.finished_at or ""}',
                ]
            )
        sections.extend(
            [
                '',
                '## Params',
                '```json',
                json.dumps(self.params, ensure_ascii=False, indent=2, sort_keys=True),
                '```',
                '',
                '## Result',
                '```json',
                json.dumps(self.result, ensure_ascii=False, indent=2, sort_keys=True),
                '```',
            ]
        )
        return '\n'.join(sections)

    def save_json(self, path: t.Union[str, Path], indent: t.Optional[int] = 2) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(indent=indent), encoding='utf-8')
        return target

    def save_text(self, path: t.Union[str, Path]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_text(), encoding='utf-8')
        return target

    def save_markdown(self, path: t.Union[str, Path]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(), encoding='utf-8')
        return target


class TestCaseStatus:
    __test__ = False

    PASSED = 'passed'
    FAILED = 'failed'
    ERROR = 'error'
    SKIPPED = 'skipped'


@dataclass
class TestCaseResult:
    __test__ = False

    name: str
    classname: str = ''
    status: str = TestCaseStatus.PASSED
    duration: t.Optional[float] = None
    message: t.Optional[str] = None
    failure_type: t.Optional[str] = None
    stdout: t.Optional[str] = None
    stderr: t.Optional[str] = None
    properties: t.Dict[str, str] = field(default_factory=dict)
    logs: t.Optional[t.List[t.Dict[str, Any]]] = None
    result_detail_files: t.List[str] = field(default_factory=list)
    result_details: t.List[ResultDetail] = field(default_factory=list)
    started_at: t.Optional[str] = None

    def add_result_detail(self, detail: ResultDetail, file_name: str = '') -> ResultDetail:
        """Attach a :class:`ResultDetail` object directly to this case.

        The object is kept in ``result_details`` (in memory). When ``file_name`` (a
        path relative to the report/log directory) is given, it is stored on the
        detail (``detail.file``) and appended to ``result_detail_files`` so the
        report can reference the saved file. Writing the file itself is left to the
        caller (e.g. ``detail.save_json``). Returns the same object for chaining.
        """
        if file_name:
            detail.file = file_name
            self.result_detail_files.append(file_name)
        self.result_details.append(detail)
        return detail


@dataclass
class TestSuiteResult:
    __test__ = False

    name: str
    test_cases: t.List[TestCaseResult] = field(default_factory=list)
    properties: t.Dict[str, str] = field(default_factory=dict)
    timestamp: t.Optional[str] = None
    package: t.Optional[str] = None
    hostname: t.Optional[str] = None
    file: t.Optional[str] = None

    @property
    def tests(self) -> int:
        return len(self.test_cases)

    @property
    def failures(self) -> int:
        return sum(1 for case in self.test_cases if case.status == TestCaseStatus.FAILED)

    @property
    def errors(self) -> int:
        return sum(1 for case in self.test_cases if case.status == TestCaseStatus.ERROR)

    @property
    def skipped(self) -> int:
        return sum(1 for case in self.test_cases if case.status == TestCaseStatus.SKIPPED)

    @property
    def time(self) -> float:
        return sum(case.duration or 0.0 for case in self.test_cases)


@dataclass
class TestSuitesResult:
    __test__ = False

    name: str = 'testsuites'
    test_suites: t.List[TestSuiteResult] = field(default_factory=list)
    properties: t.Dict[str, str] = field(default_factory=dict)

    @property
    def tests(self) -> int:
        return sum(suite.tests for suite in self.test_suites)

    @property
    def failures(self) -> int:
        return sum(suite.failures for suite in self.test_suites)

    @property
    def errors(self) -> int:
        return sum(suite.errors for suite in self.test_suites)

    @property
    def skipped(self) -> int:
        return sum(suite.skipped for suite in self.test_suites)

    @property
    def time(self) -> float:
        return sum(suite.time for suite in self.test_suites)
