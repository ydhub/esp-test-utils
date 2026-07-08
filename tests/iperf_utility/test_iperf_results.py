import os
from pathlib import Path

import pytest

from esptest.iperf_utility.iperf_results import FixRateReportOptions, IperfResult, IperfResultsRecord

try:
    import pyecharts  # noqa: F401

    has_pyecharts = True
except ImportError:
    has_pyecharts = False


def test_iperf_result_to_dict() -> None:
    res = IperfResult(avg=100, rssi=-10)
    d = res.to_dict()
    assert d['avg'] == 100
    assert d['rssi'] == -10
    assert 'type' not in d


@pytest.mark.skipif(not has_pyecharts, reason='pyecharts not installed')
def test_iperf_record(tmp_path: Path) -> None:
    record = IperfResultsRecord()
    # results data
    _res = IperfResult(avg=100, att=30, rssi=-10, ap_name='ap1')
    record.append_result(_res)
    _res = IperfResult(avg=90, att=30, rssi=-10, ap_name='ap2')
    record.append_result(_res)
    _res = IperfResult(avg=99, att=32, rssi=-11, ap_name='ap1')
    record.append_result(_res)
    _res = IperfResult(avg=89, att=32, rssi=-12, ap_name='ap2')
    record.append_result(_res)
    _res = IperfResult(avg=98, att=34, rssi=-13, ap_name='ap1')
    record.append_result(_res)
    _res = IperfResult(avg=87, att=34, rssi=-14, ap_name='ap2')
    record.append_result(_res)
    _res = IperfResult(avg=80, att=35, rssi=-14.2, ap_name='ap1')
    record.append_result(_res)
    _res = IperfResult(avg=81, att=35, rssi=-14.2, ap_name='ap2')
    record.append_result(_res)
    # test draw
    _file = str(tmp_path / 'chart1.html')
    record.draw_rssi_vs_att_chart(_file)
    assert os.path.isfile(_file)
    _file = str(tmp_path / 'chart2.html')
    record.draw_rate_vs_rssi_chart(_file, throughput_type='avg')
    assert os.path.isfile(_file)


def test_fix_rate_raw_data_marks_throughput_increase_over_tolerance() -> None:
    record = IperfResultsRecord()
    for att, throughput in [(0, 100.0), (10, 96.0), (20, 100.0), (30, 106.0)]:
        record.append_result(
            IperfResult(
                avg=throughput,
                max=throughput,
                att=att,
                rssi=-att,
                type='tcp_tx',
                config_name='perf_rate_11n_MCS0',
                ap_name='ap',
            )
        )

    markdown = record.generate_fix_rate_raw_data_markdown(['tcp_tx'], FixRateReportOptions(init_rssi=0, ap_name='ap'))

    assert '100.00 Mbps' in markdown
    assert '<font color="red">106.00 Mbps</font>' in markdown
    assert '<font color="red">100.00 Mbps</font>' not in markdown
    assert '| ATT | 0 | 10 | 20 | 30 |' in markdown
    assert '| Theoretical RSSI | 0 | -10 | -20 | -30 |' in markdown
    assert '| Scanned RSSI | 0 | -10 | -20 | -30 |' in markdown


def test_fix_rate_raw_data_marks_auto_below_fixed_max() -> None:
    record = IperfResultsRecord()
    for config_name, values in [
        ('perf_rate_11n_MCS0', {0: 100.0, 10: 90.0}),
        ('perf_rate_11n_MCS1', {0: 80.0, 10: 95.0}),
        ('perf_rate_11n_auto', {0: 94.0, 10: 90.0}),
    ]:
        for att, throughput in values.items():
            record.append_result(
                IperfResult(
                    avg=throughput,
                    max=throughput,
                    att=att,
                    rssi=-att,
                    type='tcp_tx',
                    config_name=config_name,
                    ap_name='ap',
                )
            )

    markdown = record.generate_fix_rate_raw_data_markdown(['tcp_tx'], FixRateReportOptions(init_rssi=0, ap_name='ap'))

    assert '| auto | <font color="red">94.00 Mbps</font> | <font color="red">90.00 Mbps</font> |' in markdown


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
