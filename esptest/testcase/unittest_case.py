"""Glue between :class:`unittest.TestCase` and :class:`~esptest.testcase.xunit.XunitLogger`.

This module has **no** dependency on pytest, so the base class works both under a
plain ``unittest`` runner and under pytest.
"""

import os
import unittest

import esptest.common.compat_typing as t

from .xunit import XunitLogger


def get_case_result_from_outcome(test_case: unittest.TestCase) -> t.Tuple[bool, str]:
    """Read pass/fail and a brief message for the *current* test method.

    Meant to be called from ``tearDown`` and works with both runners, whose
    outcome objects differ:

    - unittest's ``_Outcome`` keeps ``(test, exc_info)`` tuples on ``.errors``,
      populated *before* ``tearDown`` runs (``result.failures`` is only filled
      in afterwards, so it cannot be relied on here).
    - pytest keeps an ``ExceptionInfo`` list on ``_outcome.result._excinfo``.

    Returns ``(passed, message)``; ``message`` is empty when the case passed.
    """
    outcome = getattr(test_case, '_outcome', None)
    if outcome is None:
        return True, ''

    # unittest._Outcome: list of (test, exc_info); exc_info is None on success.
    for entry in getattr(outcome, 'errors', None) or []:
        exc_info = entry[1] if isinstance(entry, tuple) and len(entry) == 2 else None
        if exc_info:
            exc_type, exc_value = exc_info[0], exc_info[1]
            return False, f'{exc_type.__name__}: {exc_value}'

    result = getattr(outcome, 'result', None)
    if result is None:
        return True, ''

    # pytest: TestCaseFunction keeps ExceptionInfo list on _excinfo
    excinfo = getattr(result, '_excinfo', None)
    if excinfo:
        exc = excinfo[-1]
        value = getattr(exc, 'value', None)
        if value is not None:
            return False, f'{type(value).__name__}: {value}'
        return False, str(exc)

    # unittest fallback: TextTestResult.failures / .errors (filled post-tearDown)
    method_name = getattr(test_case, '_testMethodName', None)
    for bucket in (getattr(result, 'failures', None) or [], getattr(result, 'errors', None) or []):
        for test, traceback_str in bucket:
            if test is test_case or getattr(test, '_testMethodName', None) == method_name:
                message = traceback_str.strip().splitlines()[-1] if traceback_str else 'test failed'
                return False, message

    return True, ''


class EspTestCase(unittest.TestCase):
    """A :class:`unittest.TestCase` that streams results into an xUnit report.

    Subclasses only need to set :attr:`xunit_log_dir` (and optionally
    :attr:`target` / :attr:`config` / :attr:`xunit_suite_name`) and write plain
    ``test_*`` methods. Each case is opened in :meth:`setUp` and closed in
    :meth:`tearDown` with the result derived from the runner outcome.

    Under pytest, the ``bind_case_context`` fixture from
    ``esptest.pytest_plugin`` can inject ``target`` / ``config`` /
    ``xunit_log_dir`` onto the class automatically.

    To fold several classes (or a whole pytest session) into a *single* report,
    assign a shared :class:`~esptest.testcase.xunit.XunitLogger` to
    :attr:`xunit_logger` before :meth:`setUpClass` runs; the class then reuses
    that logger and does **not** close it (the owner is responsible for that).
    """

    #: chip target, used in the default :meth:`case_id`
    target: str = 'unknown'
    #: build/config label, used in the default :meth:`case_id`
    config: str = 'Default'
    #: directory the xUnit report (and per-case artifacts) are written under
    xunit_log_dir: str = ''
    #: xUnit suite name; defaults to the class name when empty
    xunit_suite_name: str = ''
    #: the logger; created in :meth:`setUpClass`, or set externally to share one
    xunit_logger: t.Optional[XunitLogger] = None
    #: whether this class created (and must close) :attr:`xunit_logger`
    _xunit_owns_logger: bool = False

    def case_id(self) -> str:
        """xUnit/JUnit case id, ``<target>.<config>.<method_name>`` by default."""
        return f'{self.target}.{self.config}.{self._testMethodName}'

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if cls.xunit_logger is None:
            suite_name = cls.xunit_suite_name or cls.__name__
            report_dir = os.path.join(cls.xunit_log_dir or '.', cls.__name__)
            cls.xunit_logger = XunitLogger(report_dir, suite_name=suite_name)
            cls._xunit_owns_logger = True
        else:
            cls._xunit_owns_logger = False

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._xunit_owns_logger and cls.xunit_logger is not None:
            cls.xunit_logger.close()
            cls.xunit_logger = None
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        if self.xunit_logger is not None:
            self.xunit_logger.begin_case(self.case_id(), classname=self.__class__.__name__)

    def tearDown(self) -> None:
        if self.xunit_logger is not None and self.xunit_logger.has_running_case:
            result, message = get_case_result_from_outcome(self)
            self.xunit_logger.end_case(result=result, message=message)
        super().tearDown()
