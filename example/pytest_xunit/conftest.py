"""Example: drive a single xUnit report with ``XunitLogger`` instead of pytest's junit.

- ``pytest_plugins`` enables the reusable esptest plugin (``--target`` / markers /
  the ``bind_case_context`` fixture used by ``EspTestCase``).
- ``pytest_configure`` / ``pytest_unconfigure`` call ``register_case_manager`` /
  ``unregister_case_manager`` to opt in to case filtering/export (the plugin no
  longer registers it automatically) and open/close one session-level
  ``XunitLogger`` (the shared singleton defined below).
- ``pytest_runtest_makereport`` records plain *function* cases into that logger.
- ``bind_session_logger`` (a class-scoped autouse fixture) hands the same logger
  to every ``EspTestCase`` subclass before ``setUpClass`` runs, so those cases
  report themselves into it via ``setUp`` / ``tearDown`` and are skipped by the
  ``makereport`` hook to avoid double counting.

The unified report lands at ``pytest_xunit_output/XUNIT_RESULT.xml`` and no
``--junitxml`` is needed.
"""

import os
from datetime import datetime
from typing import Any, Generator, Optional, Tuple

import pytest

from esptest.common.timestamp import timestamp_iso
from esptest.testcase import EspTestCase, XunitLogger

pytest_plugins = ['esptest.pytest_plugin']

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pytest_xunit_output')

_session_logger: Optional[XunitLogger] = None


def init_session_logger() -> XunitLogger:
    global _session_logger  # pylint: disable=global-statement
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _session_logger = XunitLogger(OUTPUT_DIR, suite_name='pytest-xunit-example')
    return _session_logger


def get_session_logger() -> Optional[XunitLogger]:
    return _session_logger


@pytest.fixture(scope='class', autouse=True)
def bind_session_logger(request: pytest.FixtureRequest) -> None:
    """Give the shared session logger to ``EspTestCase`` subclasses.

    Class-scoped autouse fixtures run before ``setUpClass``, so the class reuses
    this logger instead of creating (and owning) its own.
    """
    if request.cls is not None and issubclass(request.cls, EspTestCase):
        request.cls.xunit_logger = _session_logger


def close_session_logger() -> None:
    global _session_logger  # pylint: disable=global-statement
    if _session_logger is not None:
        _session_logger.flush(force=True)
        _session_logger.close()
        _session_logger = None


def _case_name(target: str, config: str, name: str) -> str:
    return f'{target}.{config}.{name}'


def _fn_target_config(item: pytest.Item) -> Tuple[str, str]:
    target = item.config.getoption('target', None) or 'unknown'
    config_markers = list(item.iter_markers(name='config'))
    config = config_markers[0].args[0] if config_markers else 'Default'
    return str(target), str(config)


def _short_message(longrepr: Any) -> str:
    if longrepr is None:
        return ''
    text = str(longrepr).strip()
    return text.splitlines()[-1] if text else ''


def _iso_from_epoch(epoch: float) -> str:
    return timestamp_iso(datetime.fromtimestamp(epoch))


def _set_last_case_time(logger: XunitLogger, started_at: str, duration: float) -> None:
    """Overwrite the just-recorded case with pytest's real start time and duration.

    The hook runs *after* the phase finished, so ``begin_case`` / ``end_case`` are
    called back-to-back; we replace their near-zero timing with pytest's values.
    """
    if logger.test_suite.test_cases:
        case = logger.test_suite.test_cases[-1]
        case.started_at = started_at
        case.duration = round(duration, 3)
        logger.flush(force=True)


def pytest_configure(config: pytest.Config) -> None:
    # imported lazily so pytest can assert-rewrite the plugin loaded via pytest_plugins
    from esptest.pytest_plugin import register_case_manager

    # opt in to case filtering / export (the plugin no longer does this automatically)
    register_case_manager(config)
    init_session_logger()


def pytest_unconfigure(config: pytest.Config) -> None:
    from esptest.pytest_plugin import unregister_case_manager

    unregister_case_manager(config)
    close_session_logger()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Generator[None, None, None]:
    outcome = yield
    report = outcome.get_result()  # type: ignore[attr-defined]

    # class-based EspTestCase cases self-report into the same logger
    if getattr(item, 'cls', None) is not None:
        return
    logger = get_session_logger()
    if logger is None:
        return

    target, config = _fn_target_config(item)
    name = _case_name(target, config, item.originalname)  # type: ignore[attr-defined]
    module = getattr(item, 'module', None)
    classname = module.__name__ if module is not None else ''
    # pytest's real timing for this phase (the hook runs after it finished)
    started_at = _iso_from_epoch(call.start)
    duration = call.duration

    if report.when == 'setup' and report.skipped:
        logger.begin_case(name, classname=classname)
        logger.add_skipped(_short_message(report.longrepr))
        logger.end_case()
        _set_last_case_time(logger, started_at, duration)
        return
    if report.when != 'call':
        return

    logger.begin_case(name, classname=classname)
    if report.passed:
        logger.end_case(result=True)
    else:
        logger.end_case(result=False, message=_short_message(report.longrepr))
    _set_last_case_time(logger, started_at, duration)
