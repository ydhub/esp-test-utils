import io
import logging
import os
import pty
import re
import tempfile
import time
import unittest
from typing import Any

import pytest
import serial

from esp_test_utils.adapter.dut import BaseDut
from esp_test_utils.devices.serial_dut import SerialDut


def test_base_dut_isinstance() -> None:
    class MyDut:
        def __init__(self) -> None:
            self.data = ''

        def write(self, data: str) -> None:
            self.data += data

        def expect(self, pattern: Any, timeout: int = -1) -> re.Match:
            # pylint: disable=unused-argument
            match = re.match(pattern, self.data)
            return match  # type: ignore

    def my_func(dut: BaseDut) -> None:
        dut.write('aaa')
        dut.expect(re.compile(r'aaa'))

    dut = MyDut()
    assert isinstance(dut, BaseDut)
    my_func(dut)


class TestSerialDut(unittest.TestCase):
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

    def test_set_serial_after_init(self) -> None:
        dut = SerialDut('MyDut', port=None)
        try:
            dut.serial = serial.Serial(self.serial_port, 115200, timeout=0.001)
            fd_master = os.fdopen(self.master, 'rb')
            # Test write data to serial
            dut.write('aaa')
            _data = fd_master.read1(5)
            assert _data == b'aaa'
        finally:
            dut.close()
            self._close_file_io(fd_master)

    def test_serial_dut_write(self) -> None:
        dut = SerialDut('MyDut', self.serial_port, 115200, timeout=0.001)
        fd_master = os.fdopen(self.master, 'rb')
        try:
            assert isinstance(dut, BaseDut)
            # Test write data to serial
            dut.write('aaa')
            _data = fd_master.read1(5)
            assert _data == b'aaa'
        finally:
            dut.close()
            # NOTE:
            # should close dut first, otherwise pyserial will report:
            #   device reports readiness to read but returned no data
            # Must close master io at the end of the case, otherwise the next case will fail.
            self._close_file_io(fd_master)

    def test_serial_dut_with_statement(self) -> None:
        check_thread = None
        with SerialDut('MyDut', self.serial_port, 115200, timeout=0.001) as dut:
            assert dut._pexpect_proc  # pylint: disable=protected-access
            check_thread = dut._pexpect_proc._read_thread  # pylint: disable=protected-access
            with os.fdopen(self.master, 'rb') as fd_master:
                # Test write data to serial
                dut.write('aaa')
                _data = fd_master.read1(5)
                assert _data == b'aaa'
        if check_thread:
            assert not check_thread.is_alive()

    def test_serial_dut_expect(self) -> None:
        dut = SerialDut('MyDut', self.serial_port, 115200, timeout=0.001)
        fd_master = os.fdopen(self.master, 'wb')
        try:
            # Test expect string failure
            with pytest.raises(Exception):
                dut.expect('bbb', timeout=1)
            # Test expect string success
            fd_master.write(b'bbb')
            fd_master.flush()
            # os.write(self.master, b'bbb')
            dut.expect('bbb', timeout=1)
            # Test expect bytes success
            fd_master.write(b'ccc')
            fd_master.flush()
            dut.expect(b'ccc', timeout=1)
            # Test expect regex
            fd_master.write(b'START,regex_value,END')
            fd_master.flush()
            match = dut.expect(re.compile(r'START,(\w+),END'), timeout=1)
            assert match
            assert match.group(1) == 'regex_value'
            # Test expect regex with bytes
            fd_master.write(b'START,regex_value2,END')
            fd_master.flush()
            match = dut.expect(re.compile(rb'START,(\w+),END'), timeout=1)
            assert match
            assert match.group(1) == b'regex_value2'
        finally:
            dut.close()
            self._close_file_io(fd_master)

    def test_serial_dut_log(self) -> None:
        ser_read_timeout = 0.005
        dut = SerialDut('MyDut', self.serial_port, 115200, timeout=ser_read_timeout)
        log_file = tempfile.mktemp()
        fd_master = os.fdopen(self.master, 'wb')
        try:
            # log file should be created after set log file
            dut.set_serial_log_file(log_file)
            assert os.path.isfile(log_file)
            # test one line
            fd_master.write(b'one line \r\n')
            fd_master.flush()
            time.sleep(ser_read_timeout * 2)
            with open(log_file, 'rb') as fr:
                # if we open the log file in 'r' mode, we may get \n rather than \r\n
                data = fr.read()
                assert b'one line \r\n' in data
            # test one line without \n
            fd_master.write(b'line without endl')
            fd_master.flush()
            time.sleep(ser_read_timeout * 1.5)
            with open(log_file, 'rb') as fr:
                data = fr.read()
                assert b'line without endl' not in data
            # default timeout of writting non-endl line is serial.timeout * 3
            time.sleep(ser_read_timeout * 2)
            with open(log_file, 'rb') as fr:
                data = fr.read()
                assert b'line without endl' in data
            # test line cache, write two times for one line within very short delay
            fd_master.write(b'aaa')
            fd_master.flush()
            time.sleep(ser_read_timeout)
            fd_master.write(b'bbb\r\n')
            fd_master.flush()
            time.sleep(ser_read_timeout * 2)
            with open(log_file, 'rb') as fr:
                data = fr.read()
                assert b'aaabbb\r\n' in data
            # test line cache, multiple lines at one time
            fd_master.write(b'aaa\r\nbbb\r\nccc')
            fd_master.flush()
            time.sleep(ser_read_timeout * 2)
            with open(log_file, 'rb') as fr:
                data = fr.read()
                assert b'aaabbb\r\n' in data
        except AssertionError:
            try:
                # show data in log file
                with open(log_file, 'rb') as fr:
                    data = fr.read()
                    logging.error(f'data in log file:\n{data!r}')
            except OSError:
                pass
            raise
        finally:
            dut.close()
            self._close_file_io(fd_master)
            try:
                os.remove(log_file)
            except OSError:
                pass


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main(['.', '--no-cov', '--log-cli-level=DEBUG'])
