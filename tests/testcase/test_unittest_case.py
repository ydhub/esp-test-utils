import io
import unittest
from pathlib import Path

from esptest.testcase.result import TestCaseStatus
from esptest.testcase.unittest_case import EspTestCase, get_case_result_from_outcome
from esptest.testcase.xunit import XUNIT_RESULT_FILE_NAME, parse_xunit_xml


def _run_case(case_cls: type) -> unittest.TestResult:
    suite = unittest.TestLoader().loadTestsFromTestCase(case_cls)
    runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
    return runner.run(suite)


def test_xunit_test_case_writes_report_with_mixed_results(tmp_path: Path) -> None:
    log_dir = str(tmp_path)

    class MyCase(EspTestCase):
        xunit_log_dir = log_dir
        target = 'esp32'
        config = 'Default'

        def test_pass(self) -> None:
            pass

        def test_fail(self) -> None:
            self.fail('boom')

        def test_error(self) -> None:
            raise RuntimeError('kaboom')

    result = _run_case(MyCase)
    assert result.testsRun == 3

    report_file = tmp_path / 'MyCase' / XUNIT_RESULT_FILE_NAME
    suites = parse_xunit_xml(report_file)
    cases = {c.name: c for suite in suites.test_suites for c in suite.test_cases}

    assert set(cases) == {'esp32.Default.test_pass', 'esp32.Default.test_fail', 'esp32.Default.test_error'}
    assert cases['esp32.Default.test_pass'].status == TestCaseStatus.PASSED
    assert cases['esp32.Default.test_fail'].status == TestCaseStatus.FAILED
    assert cases['esp32.Default.test_error'].status == TestCaseStatus.FAILED
    assert 'boom' in (cases['esp32.Default.test_fail'].message or '')
    assert 'kaboom' in (cases['esp32.Default.test_error'].message or '')


def test_shared_external_logger_is_reused_and_not_closed(tmp_path: Path) -> None:
    from esptest.testcase.xunit import XunitLogger

    report_dir = tmp_path / 'shared'
    shared_logger = XunitLogger(str(report_dir), suite_name='shared-suite')

    class MyCase(EspTestCase):
        xunit_logger = shared_logger
        target = 'esp32'

        def test_pass(self) -> None:
            pass

        def test_fail(self) -> None:
            self.fail('nope')

    _run_case(MyCase)

    # class must not own/close an externally provided logger
    assert MyCase._xunit_owns_logger is False
    assert MyCase.xunit_logger is shared_logger

    report_file = shared_logger.flush(force=True)
    shared_logger.close()

    suites = parse_xunit_xml(report_file)
    cases = {c.name: c for suite in suites.test_suites for c in suite.test_cases}
    assert set(cases) == {'esp32.Default.test_pass', 'esp32.Default.test_fail'}
    assert cases['esp32.Default.test_pass'].status == TestCaseStatus.PASSED
    assert cases['esp32.Default.test_fail'].status == TestCaseStatus.FAILED


def test_case_id_uses_target_config_method(tmp_path: Path) -> None:
    class MyCase(EspTestCase):
        xunit_log_dir = str(tmp_path)
        target = 'esp32c3'
        config = 'release'

        def test_something(self) -> None:
            pass

    case = MyCase(methodName='test_something')
    assert case.case_id() == 'esp32c3.release.test_something'


def test_get_case_result_from_outcome_reports_failure(tmp_path: Path) -> None:
    captured = {}

    class MyCase(EspTestCase):
        xunit_log_dir = str(tmp_path)

        def test_fail(self) -> None:
            self.fail('expected failure')

        def tearDown(self) -> None:
            captured['result'] = get_case_result_from_outcome(self)
            super().tearDown()

    _run_case(MyCase)
    passed, message = captured['result']
    assert passed is False
    assert 'expected failure' in message


def test_get_case_result_from_outcome_reports_pass(tmp_path: Path) -> None:
    captured = {}

    class MyCase(EspTestCase):
        xunit_log_dir = str(tmp_path)

        def test_pass(self) -> None:
            pass

        def tearDown(self) -> None:
            captured['result'] = get_case_result_from_outcome(self)
            super().tearDown()

    _run_case(MyCase)
    assert captured['result'] == (True, '')
