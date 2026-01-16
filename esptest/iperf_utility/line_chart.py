from typing import TYPE_CHECKING

import esptest.common.compat_typing as t

from ..common.decorators import enhance_import_error_message
from ..logger import get_logger

if TYPE_CHECKING:
    from pyecharts import options as opts

XVarType: t.TypeAlias = t.Union[int, float, str]
YVarType: t.TypeAlias = t.Union[
    t.Dict[str, t.Union[int, float, None]],
    t.Dict[str, int],
    t.Dict[str, float],
    t.Dict[str, None],
    int,
    float,
    None,
    object,  # for type hinting
]
logger = get_logger('iperf-util')


def _calculate_adjacent_diffs(series_data: t.Sequence[t.Union[int, float, None]]) -> t.List[t.Union[int, float]]:
    """Calculate adjacent differences for a series, handling None values."""
    diffs: t.List[t.Union[int, float]] = []
    last_valid_value: t.Optional[t.Union[int, float]] = None

    for i, current_value in enumerate(series_data):
        if i == 0:
            diffs.append(0)
            if current_value is not None:
                last_valid_value = current_value
            continue

        if current_value is None:
            diffs.append(0)
            continue

        if last_valid_value is not None:
            diff = current_value - last_valid_value
            diffs.append(diff)
            last_valid_value = current_value
        else:
            diffs.append(0)
            last_valid_value = current_value
    return diffs


@enhance_import_error_message('please install pyecharts or "pip install esp-test-utils[all]"')
def _create_tooltip_options(
    show_diff_tooltip: bool, y_data: t.Sequence[YVarType], y_names: t.List[str]
) -> 'opts.TooltipOpts':
    """
    create tooltip for auto calculate diff value by mouseover
    """

    import pyecharts.options as opts
    from pyecharts.commons.utils import JsCode

    # Create tooltip with diff display
    if show_diff_tooltip:
        assert y_data and y_names, 'y_data and y_names must be provided'
        all_diffs = []
        assert all(isinstance(y, dict) for y in y_data)
        for name in y_names:
            values: t.Sequence[t.Union[int, float, None]] = [y[name] for y in y_data]  # type: ignore
            all_diffs.append(_calculate_adjacent_diffs(values))
        formatter = f"""
            function(params) {{
                var alldiffs = {all_diffs};
                var tooltip = '<div style="padding: 10px;">';
                tooltip += '<b>X: ' + params[0].axisValue + '</b><br/>';
                if (Array.isArray(params)) {{
                    for (var i = 0; i < params.length; i++) {{
                        var param = params[i];
                        var seriesIndex = param.seriesIndex;
                        var seriesName = param.seriesName;
                        var seriesColor = param.color || '#2E86DE';
                        var diffs = alldiffs[seriesIndex];
                        var dataIndex = param.dataIndex;
                        var yValue = Array.isArray(param.value) ? param.value[1] : param.value;

                        if (yValue === null || yValue === undefined) {{
                            tooltip += '<span style="color: ' + seriesColor + ';">●</span> ' + seriesName;
                            tooltip += ': <b>N/A</b><br/>';
                            continue;
                        }}

                        var diff = diffs[dataIndex];
                        var diffStr = diff >= 0 ? '+' + diff.toFixed(2) : diff.toFixed(2);
                        var diffColor = diff >= 0 ? '#52c41a' : '#f5222d';
                        var diffIcon = diff >= 0 ? '▲' : '▼';

                        tooltip += '<span style="color: ' + seriesColor + ';">●</span> ' + seriesName + ': <b>';
                        tooltip += '<span style="display:inline-block;min-width:70px;">';
                        tooltip += yValue.toFixed(2) + '</span></b> ';

                        if (dataIndex > 0 && diff !== 0) {{
                            tooltip += '<span style="color: ' + diffColor + ';">' + diffIcon + '</span> ';
                            tooltip += '<span style="color:' + diffColor + '"><b>' + diffStr + '</b></span>';
                        }}
                        tooltip += '<br/>';
                    }}
                }}
                tooltip += '</div>';
                return tooltip;
            }}
        """
        tooltip_opts_obj = opts.TooltipOpts(
            trigger='axis',
            axis_pointer_type='cross',
            background_color='rgba(245, 245, 245, 0.9)',
            border_width=1,
            border_color='#ccc',
            textstyle_opts=opts.TextStyleOpts(color='#000'),
            formatter=JsCode(formatter),
            is_confine=True,
            extra_css_text='box-shadow: 0 0 3px rgba(0, 0, 0, 0.3);',
        )
    else:
        tooltip_opts_obj = opts.TooltipOpts(trigger='axis')
    return tooltip_opts_obj


@enhance_import_error_message('please install pyecharts or "pip install esp-test-utils[all]"')
def _create_axis_options(
    x_type: str, x_label: str, y_label: str, x_scale: bool = True, y_scale: bool = True
) -> t.Tuple['opts.AxisOpts', 'opts.AxisOpts']:
    """
    create axis and yaxis options
    """
    import pyecharts.options as opts

    xaxis_opts = opts.AxisOpts(
        type_=x_type,
        name=x_label,
        is_scale=x_scale,
        boundary_gap=['3%', '3%'],
        axistick_opts=opts.AxisTickOpts(is_align_with_label=True),
        splitline_opts=opts.SplitLineOpts(is_show=True),
    )

    yaxis_opts = opts.AxisOpts(
        type_='value',
        name=y_label,
        is_scale=y_scale,
        axistick_opts=opts.AxisTickOpts(is_show=True),
        splitline_opts=opts.SplitLineOpts(is_show=True),
    )

    return xaxis_opts, yaxis_opts


@enhance_import_error_message('please install pyecharts or "pip install esp-test-utils[all]"')
def draw_line_chart_basic(  # pylint: disable=too-many-positional-arguments,too-many-arguments,too-many-locals
    file_name: str,
    title: str,
    y_data: t.Sequence[YVarType],
    x_data: t.Optional[t.Sequence[XVarType]] = None,
    x_label: str = 'x',
    y_label: str = 'y',
    x_scale: bool = True,
    y_scale: bool = True,
    show_diff_tooltip: bool = False,
) -> None:
    """Draw line chart and save to file.

    Args:
        file_name (str): line chart render file name
        title (str): title of the chart
        y_data (Sequence[Dict[str, float]]): list of chart data, format eg: [{'y1': 1, 'y2': 1}, {'y1': 2, 'y2': 1}]
        x_data (Optional[Sequence[float]], optional): x data. Defaults to "range(len(y_data))".
        x_label (str, optional): x label name. Defaults to 'x'.
        y_label (str, optional): y label name. Defaults to 'y'.
        x_scale (bool, optional): x scale. Defaults to True.
        y_scale (bool, optional): y scale name. Defaults to True.
        show_diff_tooltip (bool, optional): show diff in tooltip. Defaults to False.
    """
    # pylint: disable=too-many-arguments

    import pyecharts.options as opts
    from pyecharts.charts import Line

    line = Line()

    assert len(y_data) > 0
    if not x_data:
        x_data = list(range(len(y_data)))
    assert len(x_data) == len(y_data)

    x_type = 'value'
    for x in x_data:
        if isinstance(x, str):
            x_type = 'category'
            break
    if x_type == 'category':
        x_data = list(map(str, x_data))

    line.add_xaxis(x_data)

    # Convert simple list to dict format if needed
    if isinstance(y_data[0], (int, float, type(None))):
        y_data = [{'y': var} for var in y_data]  # type: ignore

    # Collect all series data and calculate diffs
    assert isinstance(y_data[0], dict)
    y_names: t.List[str] = list(y_data[0].keys())
    for name in y_names:
        legend = name
        _data: t.Sequence[t.Union[int, float, None]] = [y[name] for y in y_data]  # type: ignore
        # Remove None values before calculating max/min, as pyecharts supports
        # Calculate diffs for this series
        _data_except_none = [y for y in _data if y is not None]
        if all((isinstance(y, (int, float)) for y in _data_except_none)):
            # show max/min
            legend += f' (max: {max(_data_except_none)}, min: {min(_data_except_none)})'
        line.add_yaxis(legend, _data, is_connect_nones=True, is_smooth=True)

    # create axis
    xaxis_opts, yaxis_opts = _create_axis_options(x_type, x_label, y_label, x_scale, y_scale)

    # add global
    line.set_global_opts(
        datazoom_opts=opts.DataZoomOpts(range_start=0, range_end=100),
        title_opts=opts.TitleOpts(title=title, pos_left='center'),
        legend_opts=opts.LegendOpts(pos_top='10%', pos_left='right', orient='vertical'),
        tooltip_opts=_create_tooltip_options(show_diff_tooltip, y_data, y_names),
        xaxis_opts=xaxis_opts,
        yaxis_opts=yaxis_opts,
        toolbox_opts=opts.ToolboxOpts(
            is_show=True,
            pos_right='5%',
            feature={
                'saveAsImage': {'title': 'Save as image'},
                'restore': {'title': 'Restore'},
                'dataZoom': {'title': {'zoom': 'Zoom', 'back': 'Restore zoom'}},
                'dataView': {'title': 'Data view', 'lang': ['Data view', 'Close', 'Refresh']},
            },
        ),
    )

    line.render(file_name)
