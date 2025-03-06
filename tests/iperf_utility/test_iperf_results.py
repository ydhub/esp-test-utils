import os
from pathlib import Path

import pytest

from esptest.iperf_utility.iperf_results import IperfResult
from esptest.iperf_utility.iperf_results import IperfResultsRecord


def test_iperf_result_to_dict() -> None:
    res = IperfResult(avg=100, rssi=-10)
    d = res.to_dict()
    assert d['avg'] == 100
    assert d['rssi'] == -10
    assert 'type' not in d


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


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
