import re
from typing import List, Optional

from ..adapter.dut import DutPort
from ..logger import get_logger
from .iperf_results import IperfResult, IperfResultsRecord

logger = get_logger('iperf-util')


class IperfDataParser:
    PC_BANDWIDTH_LOG_PATTERN = re.compile(
        r'(\d+\.\d+)\s*-\s*(\d+.\d+)\s+sec\s+[\d.]+\s+MBytes\s+([\d.]+)\s+([MK]bits/sec)'
    )
    DUT_BANDWIDTH_LOG_PATTERN = re.compile(r'([\d.]+)-\s*([\d.]+)\s+sec\s+([\d.]+)\s+([MK]bits/sec)')

    def __init__(self, raw_data: str, transmit_time: int = 0):
        self.raw_data = raw_data
        self.transmit_time = transmit_time
        self._avg_throughput: float = 0
        self._throughput_list: List[float] = []
        self.error_list: List[str] = []
        self._unit = ''
        self._parse_data()

    def _parse_data(self) -> None:
        match_list = list(self.PC_BANDWIDTH_LOG_PATTERN.finditer(self.raw_data))
        if not match_list:
            # failed to find raw data by PC pattern, it might be DUT pattern
            match_list = list(self.DUT_BANDWIDTH_LOG_PATTERN.finditer(self.raw_data))
        if not match_list:
            raise ValueError('Can not parse data!')

        _current_end = 0.0
        _interval: float = 0
        for match in match_list:
            t_start = float(match.group(1))
            t_end = float(match.group(2))
            # ignore if report time larger than given transmit time.
            if self.transmit_time and t_end > self.transmit_time:
                logger.debug(f'ignore iperf report {t_start} - {t_end}: {match.group(3)} {match.group(4)}')
                continue
            # Check if there are unexpected times
            if _current_end and t_start and t_start != _current_end:
                self.error_list.append(f'Missing iperf data from {_current_end} to {t_start}')
            _current_end = t_end
            # get match results
            self._unit = match.group(4)
            throughput = float(match.group(3))
            if not _interval and len(match_list) > 1:
                _interval = t_end - t_start
            if _interval and int(t_end - t_start) > _interval:
                # this could be the summary, got average throughput
                self._avg_throughput = throughput
                continue
            if throughput == 0.00:
                self.error_list.append(f'Throughput drop to 0 at {t_start}-{t_end}')
                # still put it into list though throughput is zero
            self._throughput_list.append(throughput)

    @property
    def avg(self) -> float:
        if self._avg_throughput:
            return self._avg_throughput
        if self._throughput_list:
            return sum(self._throughput_list) / len(self._throughput_list)
        raise ValueError('Failed to get throughput from data.')

    @property
    def max(self) -> float:
        if self._throughput_list:
            return max(self._throughput_list)
        raise ValueError('Failed to get throughput from data.')

    @property
    def min(self) -> float:
        if self._throughput_list:
            return min(self._throughput_list)
        raise ValueError('Failed to get throughput from data.')

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def throughput_list(self) -> List[float]:
        return self._throughput_list


class IperfTestBaseUtility:
    IPERF_EXTRA_OPTIONS: List[str] = []
    # IPERF_EXTRA_OPTIONS = ['-f', 'm']
    IPERF_REPORT_INTERVAL = 1
    DEF_UDP_RX_BW_LIMIT = {
        # Mbits/sec
        'esp32c2': 60,
        'esp32c3': 70,
        'esp32s2': 85,
        'esp32c6': 70,
        'default': 100,
    }
    TEST_TYPES = ['tcp_tx', 'tcp_rx', 'udp_tx', 'udp_rx']

    def __init__(
        self,
        dut: DutPort,
        remote: Optional[DutPort] = None,
    ):
        self.dut = dut
        self.remote = remote
        self.udp_rx_bw_limit = self.DEF_UDP_RX_BW_LIMIT.copy()
        self.test_types = self.TEST_TYPES.copy()
        self.results = IperfResultsRecord()

    def setup(self) -> None:
        raise NotImplementedError()

    def teardown(self) -> None:
        raise NotImplementedError()

    def run_one_case(self, test_type: str) -> IperfResult:
        raise NotImplementedError()

    def add_one_result(self, res: IperfResult) -> None:
        self.results.append_result(res)

    def run_all_cases(self) -> None:
        self.setup()
        try:
            for test_type in self.test_types:
                _res = self.run_one_case(test_type)
                self.add_one_result(_res)
        finally:
            self.teardown()
