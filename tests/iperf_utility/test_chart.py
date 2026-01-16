import logging
from pathlib import Path

import pytest

from esptest.iperf_utility import line_chart

try:
    import pyecharts  # noqa: F401

    PYECHARTS_INSTALLED = True
except ImportError:
    PYECHARTS_INSTALLED = False


@pytest.mark.skipif(PYECHARTS_INSTALLED, reason='Only run this case if pyecharts is not installed.')
def test_pyecharts_not_installed() -> None:
    with pytest.raises(ImportError) as e:
        line_chart.draw_line_chart_basic('file_name', 'title', [{'a': 1}])
    assert 'please install pyecharts' in e.value.msg


@pytest.mark.skipif(not PYECHARTS_INSTALLED, reason='Only run this case if pyecharts is installed.')
def test_draw_line_charts(tmp_path: Path) -> None:
    file_name = str(tmp_path / 'charts.html')
    y_data = [
        {'a': 1},
        {'a': 2},
        {'a': 2},
    ]
    # No exceptions
    line_chart.draw_line_chart_basic(file_name, 'title', y_data)
    # test null data
    file_name = str(tmp_path / 'charts2.html')
    y_data2 = [
        {'a': 1, 'b': 2},
        {'a': 2, 'b': None},
        {'a': None, 'b': 1},
    ]
    # No exceptions, manual check charts
    logging.info(f'test_draw_line_charts path: {str(tmp_path)}')
    line_chart.draw_line_chart_basic(file_name, 'title', y_data2)
    # test with x type str
    file_name = str(tmp_path / 'charts3.html')
    x_data = ['aa', 'bb', 'cc']
    y_data3 = [
        {'a': None},
        {'a': 2},
        {'a': 3},
    ]
    # No exceptions
    line_chart.draw_line_chart_basic(file_name, 'title', y_data3, x_data=x_data)


@pytest.mark.skipif(not PYECHARTS_INSTALLED, reason='Only run this case if pyecharts is installed.')
def test_draw_line_enhance_charts(tmp_path: Path) -> None:
    file_name = str(tmp_path / 'charts3.html')
    y_data_multi: list[dict[str, int | float | None]] = [
        {'a': None, 'b': 2, 'c': 20},
        {'a': 2, 'b': None, 'c': 10},
        {'a': None, 'b': 1, 'c': 20},
        {'a': 3, 'b': 1, 'c': 20},
        {'a': 10, 'b': 10, 'c': 200},
        {'a': 100, 'b': 100, 'c': None},
        {'a': 50, 'b': 134, 'c': 2},
        {'a': 90, 'b': 222, 'c': 12},
    ]
    # No exceptions
    line_chart.draw_line_chart_basic(
        file_name,
        'title',
        y_data_multi,
        x_label='time',
        y_label='throughput',
        x_scale=True,
        y_scale=True,
        show_diff_tooltip=True,
    )
    with open(file_name, 'r') as f:
        content = f.read()
        assert 'var alldiffs' in content
    # test null data
    file_name = str(tmp_path / 'charts4.html')
    y_data = [4, None, 5, 1, 10, None, 20]
    line_chart.draw_line_chart_basic(
        file_name,
        'title',
        y_data,
        x_label='round',
        y_label='heap',
        x_scale=True,
        y_scale=True,
        show_diff_tooltip=True,
    )
    # No exceptions, manual check charts
    logging.info(f'test_draw_line_charts path: {str(tmp_path)}')


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
