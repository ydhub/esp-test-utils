import pytest

_PLUGIN_CONFTEST = "pytest_plugins = ['esptest.pytest_plugin']\n"


def test_generic_fixtures_available(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(
        """
        import os
        import pytest

        @pytest.mark.target('esp32')
        @pytest.mark.config('Default')
        def test_names(test_case_name, session_tempdir, log_performance):
            assert test_case_name == 'esp32.Default.test_names'
            assert os.path.isdir(session_tempdir)
            log_performance('throughput', '10')
        """
    )

    result = pytester.runpytest('--target', 'esp32')

    result.assert_outcomes(passed=1)


def test_bind_case_context_injects_attributes(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(
        """
        import unittest
        import pytest

        @pytest.mark.target('esp32')
        @pytest.mark.config('release')
        class TestBound(unittest.TestCase):
            def test_context(self):
                assert self.target == 'esp32'
                assert self.config == 'release'
                assert isinstance(self.xunit_log_dir, str) and self.xunit_log_dir
        """
    )

    result = pytester.runpytest('--target', 'esp32')

    result.assert_outcomes(passed=1)
