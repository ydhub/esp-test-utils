"""Example test module exercised by ``run_example.py``.

Both case flavors write into the *same* session ``XunitLogger`` (set up in
``conftest.py``), producing one unified ``XUNIT_RESULT.xml``:

1. ``test_single_function`` -- a plain pytest function case, recorded by the
   ``pytest_runtest_makereport`` hook in ``conftest.py``.
2. ``TestExampleSuite`` -- an :class:`esptest.testcase.EspTestCase` subclass. The
   ``bind_session_logger`` autouse fixture (in ``conftest.py``) assigns the shared
   session logger to it, so its cases report themselves via ``setUp`` / ``tearDown``.
"""

import time

import pytest

from esptest.testcase import EspTestCase


@pytest.mark.target('esp32')
@pytest.mark.config('Default')
@pytest.mark.env('generic')
def test_single_function(test_case_name: str) -> None:
    """A single function case (no hardware needed)."""
    time.sleep(0.1)  # so the report shows a non-zero, real exec time
    assert test_case_name.endswith('.test_single_function')
    assert 1 + 1 == 2


@pytest.mark.target(['esp32', 'esp32s3'])
@pytest.mark.config('Default')
@pytest.mark.env('generic')
class TestExampleSuite(EspTestCase):
    """A unittest-style suite that shares the session logger (bound via fixture).

    It targets multiple chips (``esp32`` and ``esp32s3``) to show how a single
    case expands into one exported entry per target.
    """

    def test_pass(self) -> None:
        time.sleep(0.2)  # so the report shows a non-zero, real exec time
        self.assertEqual(2 + 3, 5)

    def test_expected_fail(self) -> None:
        # Intentionally failing to show a FAILED entry in the generated report.
        # Flip the expected value to 4 to make the whole example pass.
        self.assertEqual(2 + 3, 4, 'demo failure: 2 + 3 is not 4')
