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


def test_parse_iperf_data_dut_gbits() -> None:
    parser = IperfDataParser('Interval Bandwidth\n 0.0- 1.0 sec  1.05 Gbits/sec\n 1.0- 2.0 sec  1.02 Gbits/sec\n')
    assert parser.unit == 'Mbits/sec'
    assert parser.max == 1050.0
    assert parser.throughput_list == [1050.0, 1020.0]


def _read_iperf_log(name: str) -> str:
    log_file = TEST_IPERF_LOG_PATH / name
    with open(str(log_file), 'r', encoding='utf-8') as f:
        return f.read()


def test_parse_iperf3_tcp_gbits_converts_and_skips_zero_interval() -> None:
    parser = IperfDataParser(_read_iperf_log('pc_iperf3_tcp_gbits.log'))
    assert parser.unit == 'Mbits/sec'
    assert parser.max == 70800.0
    assert parser.min == 70400.0
    assert parser.avg == 70600.0
    # iperf3 3.00-3.00 sec zero-duration tail (17.3 Gbits/sec) is skipped
    assert parser.throughput_list == [70800.0, 70400.0, 70600.0]


def test_parse_iperf3_tcp_f_m_with_gbytes_transfer() -> None:
    parser = IperfDataParser(_read_iperf_log('pc_iperf3_tcp_f_m.log'))
    assert parser.unit == 'Mbits/sec'
    assert parser.max == 70417.0
    assert parser.avg == 70331.0
    assert parser.throughput_list == [70417.0, 70245.0]


def test_parse_iperf3_udp_kbytes_small_flow() -> None:
    parser = IperfDataParser(_read_iperf_log('pc_iperf3_udp_kbytes.log'))
    assert parser.unit == 'Mbits/sec'
    assert parser.max == 1.05
    assert parser.avg == 1.04
    assert parser.throughput_list == [1.05, 1.04]


def test_parse_iperf3_udp_500m() -> None:
    parser = IperfDataParser(_read_iperf_log('pc_iperf3_udp_500m.log'))
    assert parser.unit == 'Mbits/sec'
    assert parser.max == 500.0
    assert parser.avg == 499.0
    assert parser.throughput_list == [500.0, 499.0]


def test_parse_iperf3_keeps_receiver_summary() -> None:
    parser = IperfDataParser(_read_iperf_log('pc_iperf3_tcp_sender_receiver.log'))
    assert parser.avg == 70300.0
    assert parser.max == 70800.0
    assert parser.throughput_list == [70800.0, 70400.0, 70600.0]


def test_parse_iperf3_prefers_receiver_when_sender_is_last() -> None:
    log = (
        '[ ID] Interval           Transfer     Bitrate\n'
        '[  5]   0.00-1.00   sec  8.25 GBytes  70.8 Gbits/sec\n'
        '[  5]   1.00-2.00   sec  8.20 GBytes  70.4 Gbits/sec\n'
        '[  5]   0.00-2.00   sec  16.4 GBytes  70.3 Gbits/sec                  receiver\n'
        '[  5]   0.00-2.00   sec  16.5 GBytes  70.6 Gbits/sec    0             sender\n'
    )
    parser = IperfDataParser(log)
    assert parser.avg == 70300.0
    assert parser.throughput_list == [70800.0, 70400.0]


def test_parse_parallel_streams_without_sum_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    log = (
        '[ ID] Interval           Transfer     Bitrate\n'
        '[  5]   0.00-1.00   sec  4.12 GBytes  35.4 Gbits/sec\n'
        '[  7]   0.00-1.00   sec  4.13 GBytes  35.5 Gbits/sec\n'
        '[  5]   1.00-2.00   sec  4.10 GBytes  35.2 Gbits/sec\n'
        '[  7]   1.00-2.00   sec  4.10 GBytes  35.2 Gbits/sec\n'
    )
    with caplog.at_level('WARNING', logger='esptest.iperf-util'):
        parser = IperfDataParser(log)
    assert any('[SUM]' in rec.getMessage() for rec in caplog.records)
    assert len(parser.throughput_list) == 4


def test_parse_iperf3_parallel_streams_uses_sum_only() -> None:
    parser = IperfDataParser(_read_iperf_log('pc_iperf3_tcp_p2.log'))
    assert parser.unit == 'Mbits/sec'
    assert parser.max == 70900.0
    assert parser.avg == 70600.0
    assert parser.throughput_list == [70900.0, 70400.0]
    assert parser.error_list == []


def test_parse_iperf2_parallel_streams_uses_sum_only() -> None:
    parser = IperfDataParser(_read_iperf_log('pc_iperf2_tcp_p2.log'))
    assert parser.max == 107.0
    assert parser.avg == 106.0
    assert parser.throughput_list == [107.0, 105.0]
    assert parser.error_list == []


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
