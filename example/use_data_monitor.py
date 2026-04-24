# from esptest.config import EnvConfig
import logging
import re

import esptest.common.compat_typing as t
from esptest.all import DutConfig, dut_wrapper
from esptest.common.data_monitor import DataMonitor, MatchedResult

RST_REASON = {'value': ''}  # global variable to store rst reason
RST_REASON_PATTERN = re.compile(r'rst:\s*(0x\w+\s*\(\w+\))')
CHIP_VERSION_PATTERN = re.compile(r'Chip rev:\s*(v[\d\.]+)')


def rst_reason_callback(matched_result: MatchedResult) -> None:
    logging.critical(f'rst_reason_callback: {matched_result}')
    assert matched_result.match
    assert isinstance(matched_result.match, re.Match)
    RST_REASON['value'] = matched_result.match.group(1)
    logging.critical(f'RST reason: {matched_result.match.group(1)}')


class MonitorChipVersion(DataMonitor):  # pylint: disable=super-init-not-called
    pattern = r'Chip ID: ([\da-fA-F]+)'

    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.monitor = DataMonitor(CHIP_VERSION_PATTERN, self.monitor_callback)
        self.matched_results: t.List[MatchedResult] = []
        self.version = ''

    def append_data(self, port_name: str, data: t.AnyStr, timestamp: float = 0) -> None:
        return self.monitor.append_data(port_name, data, timestamp)

    def monitor_callback(self, matched_result: MatchedResult) -> None:
        logging.critical(f'MonitorChipVersion callback: {matched_result}')
        self.matched_results.append(matched_result)
        assert matched_result.match
        assert isinstance(matched_result.match, re.Match)
        self.version = matched_result.match.group(1)


def dut_reboot_test_with_monitor() -> None:
    chip_version_checker = MonitorChipVersion()
    rst_reason_monitor = DataMonitor(RST_REASON_PATTERN, rst_reason_callback)

    _config = DutConfig(
        name='JAP1', device='/dev/ttyUSB0', baudrate=115200, monitors=[chip_version_checker.monitor, rst_reason_monitor]
    )
    # create dut with customer class
    with dut_wrapper(_config) as dut:
        dut.write_line('reboot', end='\r\n')
        dut.expect(r'ready')

    logging.critical(f'Chip version: {chip_version_checker.version}')
    logging.critical(f'RST reason: {RST_REASON["value"]}')


if __name__ == '__main__':
    dut_reboot_test_with_monitor()
