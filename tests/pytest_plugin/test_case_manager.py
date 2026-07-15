import json

import pytest

_PLUGIN_CONFTEST = """
pytest_plugins = ['esptest.pytest_plugin']


def pytest_configure(config):
    from esptest.pytest_plugin import register_case_manager

    register_case_manager(config)


def pytest_unconfigure(config):
    from esptest.pytest_plugin import unregister_case_manager

    unregister_case_manager(config)
"""

_SAMPLE_TESTS = """
import pytest


@pytest.mark.target('esp32')
@pytest.mark.env('generic')
@pytest.mark.config('Default')
def test_one():
    pass


@pytest.mark.target('esp32s2')
@pytest.mark.env('generic')
@pytest.mark.config('Default')
def test_two():
    pass
"""


def test_target_filtering_selects_matching_cases(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(_SAMPLE_TESTS)

    result = pytester.runpytest('--target', 'esp32')

    result.assert_outcomes(passed=1)


def test_no_target_runs_all_cases(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(_SAMPLE_TESTS)

    result = pytester.runpytest()

    result.assert_outcomes(passed=2)


def test_env_filtering(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.target('esp32')
        @pytest.mark.env('generic')
        def test_generic():
            pass

        @pytest.mark.target('esp32')
        @pytest.mark.env('wifi')
        def test_wifi():
            pass
        """
    )

    result = pytester.runpytest('--target', 'esp32', '--env', 'wifi')

    result.assert_outcomes(passed=1)


def test_export_case_names(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(_SAMPLE_TESTS)
    out = pytester.path / 'names.txt'

    result = pytester.runpytest('--export-case-names', str(out))

    assert result.ret == 0
    assert out.read_text().splitlines() == ['esp32.Default.test_one', 'esp32s2.Default.test_two']


def test_export_cases_json_with_custom_hook(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        _PLUGIN_CONFTEST
        + """
def pytest_esptest_export_case(item, case, config):
    case['sdk'] = 'v5.5'
"""
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.target(['esp32', 'esp32s2'])
        @pytest.mark.env('generic')
        @pytest.mark.config('Default')
        @pytest.mark.timeout(120)
        def test_alpha():
            pass
        """
    )
    out = pytester.path / 'cases.json'

    result = pytester.runpytest('--export-cases', str(out))

    assert result.ret == 0
    data = json.loads(out.read_text())
    cases = data['cases']
    assert [c['name'] for c in cases] == ['esp32.Default.test_alpha', 'esp32s2.Default.test_alpha']
    assert all(c['sdk'] == 'v5.5' for c in cases)
    assert cases[0]['target'] == 'ESP32'
    assert cases[0]['config'] == 'Default'
    assert cases[0]['env'] == 'generic'
    assert cases[0]['timeout'] == 120
    assert cases[0]['file'].endswith('.py')


def test_run_case_file_filtering(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_PLUGIN_CONFTEST)
    pytester.makepyfile(_SAMPLE_TESTS)
    case_file = pytester.path / 'run.txt'
    case_file.write_text('# only run test_one\nesp32.Default.test_one\n')

    result = pytester.runpytest('--target', 'esp32', '--run-case-file', str(case_file))

    result.assert_outcomes(passed=1)
