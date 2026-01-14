import esptest.common.compat_typing as t

from ..common.decorators import enhance_import_error_message
from ..logger import get_logger

XVarType: t.TypeAlias = t.Union[int, float, str]
YVarType: t.TypeAlias = t.Union[
    t.Dict[str, t.Union[int, float, None]], t.Dict[str, int], t.Dict[str, float], t.Dict[str, None]
]
logger = get_logger('iperf-util')


@enhance_import_error_message('please install pyecharts or "pip install esp-test-utils[all]"')
def draw_line_chart_basic(  # pylint: disable=too-many-positional-arguments
    file_name: str,
    title: str,
    y_data: t.Sequence[YVarType],
    x_data: t.Optional[t.Sequence[XVarType]] = None,
    x_label: str = 'x',
    y_label: str = 'y',
    x_scale: bool = True,
    y_scale: bool = True,
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
    """
    # pylint: disable=too-many-arguments
    import pyecharts.options as opts
    from pyecharts.charts import Line

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

    line = Line()
    line.add_xaxis(x_data)

    y_names = y_data[0].keys()
    for name in y_names:
        legend = name
        _data = [y[name] for y in y_data]
        # Remove None values before calculating max/min, as pyecharts supports connect None values.
        _data_except_none = [y for y in _data if y is not None]
        if all((isinstance(y, (int, float)) for y in _data_except_none)):
            # show max/min
            legend += f' (max: {max(_data_except_none)}, min: {min(_data_except_none)})'
        line.add_yaxis(legend, _data, is_connect_nones=True, is_smooth=True)

    line.set_global_opts(
        datazoom_opts=opts.DataZoomOpts(range_start=0, range_end=100),
        title_opts=opts.TitleOpts(title=title, pos_left='center'),
        legend_opts=opts.LegendOpts(pos_top='10%', pos_left='right', orient='vertical'),
        tooltip_opts=opts.TooltipOpts(trigger='axis'),
        xaxis_opts=opts.AxisOpts(
            type_=x_type,
            name=x_label,
            is_scale=x_scale,
            boundary_gap=['3%', '3%'],
            axistick_opts=opts.AxisTickOpts(is_align_with_label=True),
            splitline_opts=opts.SplitLineOpts(is_show=True),
        ),
        yaxis_opts=opts.AxisOpts(
            type_='value',
            name=y_label,
            is_scale=y_scale,
            axistick_opts=opts.AxisTickOpts(is_show=True),
            splitline_opts=opts.SplitLineOpts(is_show=True),
        ),
    )
    line.render(file_name)
