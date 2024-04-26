# from esp_test_utils.config import EnvConfig
import logging
import re

from serial import Serial

from esp_test_utils import dut_wrapper
from esp_test_utils.adapter.dut import DutPort


class JapDut(DutPort):
    def jap_get_ip(self, ssid: str, password: str) -> str:
        # self.write_line('wifi_mode sta')
        # self.expect('OK')
        self.write_line(f'sta_connect {ssid} {password}')
        match = self.expect(re.compile(r'IPv4 address: ([\.\d]+)[^\.\d]'))
        return match.group(1)


def jap_test() -> None:
    ser = Serial('/dev/ttyUSB0', 115200, timeout=0.01)
    with dut_wrapper(ser, 'JAP', log_file='dut.log', wrap_cls=JapDut) as dut:
        ip = dut.jap_get_ip('testap111', '1234567890')
        logging.critical(f'Jap success. IP: {ip}')


if __name__ == '__main__':
    jap_test()
