import pathlib

import pytest

from esptest.iperf_utility.iperf_test import IperfDataParser

TEST_IPERF_LOG_PATH = pathlib.Path(__file__).parent / '_files'


def test_parse_iperf_data_pc() -> None:
    # Parse pc iperf rx log
    log_file = str(TEST_IPERF_LOG_PATH / 'pc_iperf_rx.log')
    with open(log_file, 'r', encoding='utf-8') as f:
        data = f.read()
    parser = IperfDataParser(data)
    assert parser.max == 107.0
    assert parser.avg == 105.0
    assert len(parser.throughput_list) == 30
    assert parser.throughput_list[0] == 107.0
    assert parser.throughput_list[1] == 105.0
    # Parse pc iperf rx log (interval=2seconds)
    log_file = str(TEST_IPERF_LOG_PATH / 'pc_iperf_rx2.log')
    with open(log_file, 'r', encoding='utf-8') as f:
        data = f.read()
    parser = IperfDataParser(data)
    assert parser.max == 106.0
    assert parser.avg == 105.0
    assert len(parser.throughput_list) == 15
    assert parser.throughput_list[0] == 106.0
    assert parser.throughput_list[1] == 105.0


def test_parse_iperf_data_dut() -> None:
    # Parse dut iperf rx log (interval=1seconds)
    log_file = str(TEST_IPERF_LOG_PATH / 'dut_iperf_rx1.log')
    with open(log_file, 'r', encoding='utf-8') as f:
        data = f.read()
    parser = IperfDataParser(data, transmit_time=10)
    assert parser.max == 4.68
    assert 4.3 < parser.avg < 4.4
    assert len(parser.throughput_list) == 10
    assert parser.throughput_list[0] == 3.97
    assert parser.throughput_list[1] == 3.82

    # Parse dut iperf rx log (interval=1seconds)
    log_file = str(TEST_IPERF_LOG_PATH / 'dut_iperf_rx2.log')
    with open(log_file, 'r', encoding='utf-8') as f:
        data = f.read()
    parser = IperfDataParser(data)
    assert parser.max == 13.6
    assert 13.2 < parser.avg < 13.3
    assert len(parser.throughput_list) == 20
    assert parser.throughput_list[0] == 13.13
    assert parser.throughput_list[1] == 13.04


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
