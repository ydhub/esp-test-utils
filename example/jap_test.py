# from esptest.config import EnvConfig
import logging
import re
import time

from esptest.all import DutConfig, dut_wrapper
from esptest.all import EspDut as Dut


class JapDut(Dut):
    # customer methods
    def jap_get_ip(self, ssid: str, password: str) -> str:
        # self.write_line('wifi_mode sta')
        # self.expect('OK')
        self.write_line(f'sta_connect {ssid} {password}')
        match = self.expect(re.compile(r'IPv4 address: ([\.\d]+)[^\.\d]'))
        return match.group(1)


def jap_test() -> None:
    _config = DutConfig(
        name='JAP1',
        device='/dev/ttyUSB0',
        baudrate=115200,
    )
    # create dut with customer class
    with dut_wrapper(_config, wrap_cls=JapDut) as dut:
        # no reset by default
        # connect wifi AP
        ip = dut.jap_get_ip('testap111', '1234567890')
        logging.critical(f'Jap success. IP: {ip}')


def jap_test_download_bin() -> None:
    _config = DutConfig(
        name='JAP1',
        device='/dev/ttyUSB0',
        support_esptool=True,
        baudrate=115200,
        bin_path='~/test_bin/ESP32C5/QACT_WIFI_Default',
        log_path='./dut_logs',
    )

    with dut_wrapper(_config, wrap_cls=JapDut) as dut:
        # download bin
        dut.download_bin()
        # boot finished, need delay for app_main ready
        time.sleep(5)
        # connect wifi AP
        ip = dut.jap_get_ip('testap111', '1234567890')
        logging.critical(f'Jap success. IP: {ip}')


if __name__ == '__main__':
    jap_test()
    jap_test_download_bin()
