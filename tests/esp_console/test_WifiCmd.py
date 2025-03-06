import io
import logging
import os
import pathlib
import pty
import re
import threading
import time
import unittest

import pytest
import serial

from esptest import dut_wrapper
from esptest.esp_console.wifi_cmd import ConnectedInfo
from esptest.esp_console.wifi_cmd import WifiCmd

SERIAL_PORT = os.getenv('ESPPORT', '/dev/ttyUSB0')
TEST_FILES_PATH = pathlib.Path(__file__).resolve().parent / '_files'


# This test does not need target
def test_wifi_cmd_get_version_text() -> None:
    text_sta_scan = """

sta_scan  [<ssid>] [-n <channel>]
  WiFi is station mode, Scan APs
        <ssid>  SSID of AP
  -n, --channel=<channel>  channel of AP

"""
    text_scan = text_sta_scan.replace('sta_scan', 'scan')
    with pytest.raises(AssertionError):
        WifiCmd.detect_version(None, help_text='invalid textual')
    version = WifiCmd.detect_version(None, help_text=text_sta_scan)
    assert version == 'v1.0'
    version = WifiCmd.detect_version(None, help_text=text_scan)
    assert version == 'v0.0'
    version = WifiCmd.detect_version(None, help_text=text_sta_scan + text_scan)
    assert version == 'v0.1'


@pytest.mark.target_test
@pytest.mark.env('wifi_cmd')
def test_wifi_cmd_get_version_dut() -> None:
    ser = serial.Serial(SERIAL_PORT, 115200, timeout=0.001)
    with dut_wrapper(ser) as dut:
        dut.write(b'help\r\n')
        time.sleep(2)
        _match = dut.expect(re.compile('.+', re.DOTALL), timeout=0)
        assert _match
        help_log = _match.group(0)
        logging.debug(f'help_log: {help_log}')
        assert '\nscan ' in help_log
        assert '\nsta_scan ' in help_log
        version = WifiCmd.detect_version(dut)
        assert version == '0.1'


@pytest.mark.target_test
@pytest.mark.env('wifi_cmd')
def test_wifi_cmd_sta_connect_dut() -> None:
    ser = serial.Serial(SERIAL_PORT, 115200, timeout=0.001)
    test_ssid = os.environ['TEST_AP_SSID']
    test_passwd = os.environ['TEST_AP_PASSWD']
    with dut_wrapper(ser) as dut:
        dut.write(b'\r\n')
        time.sleep(0.1)
        dut.write(b'sta_disconnect\r\n')
        time.sleep(0.2)
        conn_cmd = WifiCmd.gen_connect_cmd(test_ssid, test_passwd)
        info = WifiCmd.connect_to_ap(
            dut,
            conn_cmd,
            timeout=30,
        )
        assert info.ssid == test_ssid
        assert info.channel == int(os.environ['TEST_AP_CHANNEL'])


class TestWifiCmd(unittest.TestCase):
    def setUp(self) -> None:
        self.master, self.slave = pty.openpty()
        self.serial_port = os.ttyname(self.slave)
        logging.debug(f'openpty master:{self.master} slave:{self.slave} serial_port:{self.serial_port}')
        self.dut_obj = None

    def tearDown(self) -> None:
        try:
            os.close(self.master)
        except OSError:
            # file descriptor may be closed by `with os.fdopen()` or _close_file_io()
            pass
        try:
            os.close(self.slave)
        except OSError:
            # file descriptor may be closed by `serial.close()`
            pass

    @staticmethod
    def _close_file_io(file_io: io.BufferedIOBase) -> None:
        try:
            file_io.close()
        except OSError:
            pass

    @staticmethod
    def _serial_append_log(fw_master: io.BufferedIOBase, log_file: str) -> None:
        with open(str(TEST_FILES_PATH / log_file), 'rb') as f:
            data = f.read()
        try:
            while len(data) > 2048:
                fw_master.write(data[:2048])
                data = data[2048:]
                fw_master.flush()
                time.sleep(0.01)
            fw_master.write(data)
            fw_master.flush()
        except IOError:
            pass

    def _test_wifi_cmd_sta_connect_suc(self, log_file: str) -> ConnectedInfo:
        ser = serial.Serial(self.serial_port, 115200, timeout=0.001)
        fw_master = os.fdopen(self.master, 'wb')
        try:
            with dut_wrapper(ser, 'MyDut') as dut:
                kwargs = {'fw_master': fw_master, 'log_file': log_file}
                timer = threading.Timer(0.5, self._serial_append_log, kwargs=kwargs)
                timer.start()

                conn_cmd = WifiCmd.gen_connect_cmd('testap-11', password='00000000')
                info = WifiCmd.connect_to_ap(
                    dut,
                    conn_cmd,
                    timeout=5,
                )
                assert info.ssid == 'testap-11'
                assert info.channel == 11
                timer.cancel()
                timer.join()
                return info
        finally:
            self._close_file_io(fw_master)

    def test_wifi_cmd_sta_connect_v1(self) -> None:
        info = self._test_wifi_cmd_sta_connect_suc('wifi_cmd_connected_1.log')
        assert info.bssid == '30:5a:3a:74:90:f0'
        assert info.rssi == -33

    def test_wifi_cmd_sta_connect_v2(self) -> None:
        info = self._test_wifi_cmd_sta_connect_suc('wifi_cmd_connected_2.log')
        assert info.bssid == '30:5a:3a:74:90:f0'
        assert info.rssi == -31


if __name__ == '__main__':
    # Enable target test for local debugging
    os.environ['RUN_TARGET_TEST'] = '1'
    os.environ['TEST_AP_SSID'] = 'testap-11'
    os.environ['TEST_AP_PASSWD'] = '1234567890'
    os.environ['TEST_AP_CHANNEL'] = '11'
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
