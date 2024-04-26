import io
import logging
import os
import pty
import re
import tempfile
import time
import unittest

import pytest
import serial

from esp_test_utils import dut_wrapper
from esp_test_utils.adapter.base_port import ExpectTimeout
from esp_test_utils.adapter.base_port import RawPort
from esp_test_utils.adapter.dut import DutPort
from esp_test_utils.adapter.dut.serial_dut import SerialPort
from esp_test_utils.devices.serial_dut import SerialDut


def test_base_dut_isinstance() -> None:
    class MyPort:
        def __init__(self) -> None:
            self._data = b''

        def write_bytes(self, data: bytes) -> None:
            self._data += data

        def read_bytes(self, timeout: int = -1) -> bytes:
            assert timeout > 0
            time.sleep(timeout)
            _data = self._data
            self._data = b''
            return _data

    def my_func(dut: DutPort) -> None:
        dut.write('aaa')
        dut.expect(re.compile(r'aaa'))

    my_port = MyPort()
    assert isinstance(my_port, RawPort)
    with dut_wrapper(my_port, 'MyDut') as dut:
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

    def test_serial_port_class(self) -> None:
        ser = SerialPort(self.serial_port, 115200, timeout=0.001)
        assert isinstance(ser, RawPort)

    def test_set_serial_after_init(self) -> None:
        dut = SerialDut(None, name='MyDut')
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
        ser = serial.Serial(self.serial_port, 115200, timeout=0.001)
        dut = SerialDut(ser, 'MyDut')
        fd_master = os.fdopen(self.master, 'rb')
        try:
            assert isinstance(dut, DutPort)
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
        ser = serial.Serial(self.serial_port, 115200, timeout=0.001)
        with SerialDut(ser, 'MyDut') as dut:
            assert dut._pexpect_proc  # pylint: disable=protected-access
            check_thread = dut._pexpect_proc._read_thread  # pylint: disable=protected-access
            with os.fdopen(self.master, 'rb') as fd_master:
                # Test write data to serial
                dut.write('aaa')
                _data = fd_master.read1(5)
                assert _data == b'aaa'
        if check_thread:
            assert not check_thread.is_alive()

    def test_dut_wrapper_raise_timeout(self) -> None:
        ser = serial.Serial(self.serial_port, 115200, timeout=0.001)
        ser_dut = SerialDut(ser, 'MyDut')
        with dut_wrapper(ser_dut) as dut:
            # Test expect string failure
            with pytest.raises(ExpectTimeout):
                dut.expect('bbb', timeout=1)

    def test_serial_dut_expect(self) -> None:
        t0 = time.perf_counter()
        ser = serial.Serial(self.serial_port, 115200, timeout=0.001)
        dut = SerialDut(ser, 'MyDut')
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
            match1 = dut.expect(re.compile(r'START,(\w+),END'), timeout=1)
            assert match1
            assert match1.group(1) == 'regex_value'
            # Test expect regex with bytes
            fd_master.write(b'START,regex_value2,END')
            fd_master.flush()
            match2 = dut.expect(re.compile(rb'START,(\w+),END'), timeout=1)
            assert match2
            assert match2.group(1) == b'regex_value2'
            # Test expect read all output dat
            # Test regex flags
            fd_master.write(b'data1 data1 data1 \r\n')
            fd_master.flush()
            time.sleep(0.1)
            fd_master.write(b'data2 data2 data2')
            fd_master.flush()
            time.sleep(0.1)
            match3 = dut.expect(re.compile(r'.+', re.DOTALL), timeout=0)
            assert match3
            assert match3.group(0) == 'data1 data1 data1 \r\ndata2 data2 data2'
            # Test expect more than one match
            # Hop to got match twice
            fd_master.write(b'match1, match2\n')
            fd_master.flush()
            time.sleep(0.1)
            match4 = dut.expect(re.compile(r'(match1|match2)', re.DOTALL), timeout=0)
            assert match4
            assert match4.group(0) == 'match1'
            match5 = dut.expect(re.compile(r'(match1|match2)', re.DOTALL), timeout=0)
            assert match5
            assert match5.group(0) == 'match2'
        finally:
            dut.close()
            self._close_file_io(fd_master)
        # Check Total time, All expect should block no more than one seconds other than the failure one
        assert time.perf_counter() - t0 < 2

    def test_serial_dut_data_cache(self) -> None:
        ser_read_timeout = 0.003
        ser = serial.Serial(self.serial_port, 115200, timeout=ser_read_timeout)
        dut = SerialDut(ser, 'MyDut')
        fd_master = os.fdopen(self.master, 'wb')
        try:
            data_cache = dut.data_cache
            assert data_cache == ''
            # port data
            fd_master.write(b'bbb')
            fd_master.flush()
            time.sleep(ser_read_timeout * 2)
            # get data cache does not clear port buffer
            data_cache = dut.data_cache
            assert data_cache == 'bbb'
            data_cache = dut.data_cache
            assert data_cache == 'bbb'
            # Clear port buffer
            dut.flush_data()
            data_cache = dut.data_cache
            assert data_cache == ''
            with pytest.raises(Exception):
                dut.expect('bbb', timeout=1)
            # Test expect bytes success
            fd_master.write(b'ccc')
            fd_master.flush()
            time.sleep(ser_read_timeout * 2)
            bytes_cache = dut.read_all_bytes(flush=False)
            assert bytes_cache == b'ccc'
            bytes_cache = dut.read_all_bytes(flush=False)
            assert bytes_cache == b'ccc'
        finally:
            dut.close()
            self._close_file_io(fd_master)

    def test_serial_dut_log(self) -> None:
        ser_read_timeout = 0.005
        ser = serial.Serial(self.serial_port, 115200, timeout=ser_read_timeout)
        log_file = tempfile.mktemp()
        dut = SerialDut(ser, 'MyDut', log_file=log_file)
        fd_master = os.fdopen(self.master, 'wb')
        try:
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
            time.sleep(ser_read_timeout * 2)
            with open(log_file, 'rb') as fr:
                data = fr.read()
                assert b'line without endl' not in data
            # default timeout of writting non-endl line is serial.timeout * 3
            time.sleep(ser_read_timeout * 5)
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
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
