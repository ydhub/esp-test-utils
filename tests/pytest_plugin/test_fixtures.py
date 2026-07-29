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


def test_opts_fixture_parses_repeated_values(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(
        """
        def test_opts(opts):
            assert opts == {
                'sdk': 'v5.5',
                'mode': 'release=debug',
            }
        """
    )

    result = pytester.runpytest(
        '--opts',
        'sdk=old',
        '--opts',
        'sdk=v5.5',
        '--opts',
        'mode=release=debug',
    )

    result.assert_outcomes(passed=1)


def test_opts_fixture_defaults_to_empty_dict(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(
        """
        def test_opts(opts):
            assert opts == {}
        """
    )

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)


@pytest.mark.parametrize('invalid_value', ['missing-separator', '=empty-key'])
def test_opts_fixture_rejects_invalid_values(pytester: pytest.Pytester, invalid_value: str) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(
        """
        def test_opts(opts):
            pass
        """
    )

    result = pytester.runpytest('--opts', invalid_value)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(['*invalid --opts value*expected KEY=VALUE*'])


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
                assert self.opts == {'sdk': 'v5.5', 'mode': 'release'}
        """
    )

    result = pytester.runpytest(
        '--target',
        'esp32',
        '--opts',
        'sdk=v5.5',
        '--opts',
        'mode=release',
    )

    result.assert_outcomes(passed=1)


def test_bind_case_context_opts_default_empty(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(
        """
        import unittest
        import pytest

        @pytest.mark.target('esp32')
        class TestBound(unittest.TestCase):
            def test_context(self):
                assert self.opts == {}
        """
    )

    result = pytester.runpytest('--target', 'esp32')

    result.assert_outcomes(passed=1)
