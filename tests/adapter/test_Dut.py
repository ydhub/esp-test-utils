import io
import logging
import os
import re
import sys
import tempfile
import time
import types
import unittest
from typing import Optional

if sys.platform != 'win32':
    import pty

import pytest
import serial

import esptest.common.compat_typing as t
from esptest import dut_wrapper
from esptest.adapter.dut import DutBase
from esptest.adapter.dut.create_dut import create_dut
from esptest.adapter.dut.dut_base import DutConfig
from esptest.adapter.dut.esp_dut import EspDut
from esptest.adapter.port.base_port import BasePort, ExpectTimeout, RawPort, g
from esptest.adapter.port.serial_port import SerialExt
from esptest.adapter.port.shell_port import ShellRaw
from esptest.common.data_monitor import DataMonitor
from esptest.devices.serial_dut import SerialDut  # deprecated


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

    def my_func(dut: DutBase) -> None:
        dut.write('aaa')
        dut.expect(re.compile(r'aaa'))

    my_port = MyPort()
    assert isinstance(my_port, RawPort)
    with dut_wrapper(my_port, 'MyDut') as dut:
        my_func(dut)


@pytest.mark.skipif(sys.platform == 'win32', reason='wexpect has issues with PowerShell/cmd.exe on Windows')
def test_create_dut_with_monitor_in_dut_config() -> None:
    monitor = DataMonitor('hello')
    dut_config = DutConfig(
        name='MyDut',
        opened_port=ShellRaw(cmd='/bin/bash'),
        monitors=[monitor],
    )
    dut: DutBase = create_dut(dut_config)
    try:
        assert dut._base_port_proxy is not None  # pylint: disable=protected-access
        assert dut._base_port_proxy.spawn is not None  # pylint: disable=protected-access
        assert dut._base_port_proxy.spawn._monitors == [monitor]  # pylint: disable=protected-access
        dut.write_line('echo hello')
        time.sleep(0.1)  # wait for redirect thread to consume output
        # monitor should be matched even expect is not called
        assert monitor.matched_count >= 1
        assert monitor.matched_ports[-1] == dut.name
    finally:
        dut.close()


@pytest.mark.skipif(sys.platform == 'win32', reason='wexpect has issues with PowerShell/cmd.exe on Windows')
def test_dut_add_remove_clear_monitor() -> None:
    monitor_a = DataMonitor('hello')
    monitor_b = DataMonitor('world')
    dut_config = DutConfig(
        name='MyDut',
        opened_port=ShellRaw(cmd='/bin/bash'),
    )
    dut: DutBase = create_dut(dut_config)
    try:
        assert dut._base_port_proxy is not None  # pylint: disable=protected-access
        assert dut._base_port_proxy.spawn is not None  # pylint: disable=protected-access
        assert dut.monitors == []
        assert dut._base_port_proxy.spawn._monitors is None  # pylint: disable=protected-access

        dut.add_monitor(monitor_a)
        assert dut.monitors == [monitor_a]
        assert dut._base_port_proxy.spawn._monitors == [monitor_a]  # pylint: disable=protected-access

        dut.add_monitor(monitor_a)
        assert dut.monitors == [monitor_a]
        assert dut._base_port_proxy.spawn._monitors == [monitor_a]  # pylint: disable=protected-access

        dut.add_monitor(monitor_b)
        assert dut.monitors == [monitor_a, monitor_b]
        assert dut._base_port_proxy.spawn._monitors == [monitor_a, monitor_b]  # pylint: disable=protected-access

        dut.remove_monitor(monitor_a)
        assert dut.monitors == [monitor_b]
        assert dut._base_port_proxy.spawn._monitors == [monitor_b]  # pylint: disable=protected-access

        dut.remove_monitor(monitor_a)
        assert dut.monitors == [monitor_b]
        assert dut._base_port_proxy.spawn._monitors == [monitor_b]  # pylint: disable=protected-access

        dut.clear_monitors()
        assert dut.monitors == []
        assert dut._base_port_proxy.spawn._monitors == []  # pylint: disable=protected-access
    finally:
        dut.close()


def test_esp_dut_remote_url_uses_serial_for_url() -> None:
    base_port = None
    dut = object.__new__(EspDut)
    dut._kwargs = {}
    dut._raw_port = None
    dut._dut_config = DutConfig(
        name='remote_dut',
        device='loop://',
        baudrate=74880,
        serial_configs={'timeout': 0.123, 'rtscts': False},
        support_esptool=False,
    )
    try:
        base_port = EspDut._create_base_port(dut)
        assert isinstance(base_port, BasePort)
        assert isinstance(dut._raw_port, serial.SerialBase)
        assert dut._raw_port.port == 'loop://'
        assert dut._raw_port.is_open is True
        assert dut._raw_port.rts is False
        assert dut._raw_port.dtr is False
        # real serial_for_url(loop://) should read back what we wrote
        dut._raw_port.write(b'hello')
        assert dut._raw_port.read(5) == b'hello'
    finally:
        if base_port:
            base_port.close()


def test_esp_dut_close_closes_serial_base_raw_port() -> None:
    raw_port = serial.SerialBase.__new__(serial.SerialBase)
    close_called = {'count': 0}

    def _close(_self) -> None:  # type: ignore
        close_called['count'] += 1

    raw_port.close = types.MethodType(_close, raw_port)  # type: ignore

    class FakeBasePort:
        def __init__(self, rp: t.Optional[serial.SerialBase]) -> None:
            self.raw_port = rp
            self.close_called = 0

        def close(self) -> None:
            self.close_called += 1

    base_port = FakeBasePort(raw_port)
    dut = object.__new__(EspDut)
    dut._base_port_proxy: t.Optional[BasePort] = base_port  # type: ignore
    dut._close_base_port_when_exit = True
    dut._close_raw_port_when_exit = True

    EspDut.close(dut)

    assert base_port.close_called == 1
    assert close_called['count'] == 1


def test_dut_base_change_serial_config_proxies_to_base_port() -> None:
    class FakeBasePort:
        def __init__(self) -> None:
            self.kwargs: t.Optional[t.Dict[str, t.Any]] = None

        def change_serial_config(self, **kwargs: t.Any) -> None:
            self.kwargs = kwargs

    base_port = FakeBasePort()
    dut = object.__new__(DutBase)
    dut._base_port_proxy = base_port  # type: ignore

    DutBase.change_serial_config(dut, baudrate=74880)
    assert base_port.kwargs == {'baudrate': 74880}


def test_dut_base_change_serial_config_raises_without_proxy() -> None:
    dut = object.__new__(DutBase)
    dut._base_port_proxy = None
    with pytest.raises(OSError, match='change_serial_config is not available'):
        DutBase.change_serial_config(dut, baudrate=115200)


def test_dut_base_stop_redirect_thread_returns_false_without_proxy() -> None:
    dut = object.__new__(DutBase)
    dut._base_port_proxy = None
    assert DutBase.stop_redirect_thread(dut) is False


def test_dut_base_write_raises_without_proxy() -> None:
    dut = object.__new__(DutBase)
    dut._base_port_proxy = None
    with pytest.raises(OSError, match='write is not available, port not configured'):
        DutBase.write(dut, 'x')


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not support pty')
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
        ser = SerialExt(self.serial_port, 115200, timeout=0.001)
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
            assert isinstance(dut, BasePort)
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
            assert dut._pexpect_spawn  # pylint: disable=protected-access
            check_thread = dut._pexpect_spawn._read_thread  # pylint: disable=protected-access
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

    def test_serial_dut_expect_maxread(self) -> None:
        t0 = time.perf_counter()
        ser = serial.Serial(self.serial_port, 115200, timeout=0.001)
        dut = SerialDut(ser, 'MyDut', maxread=1024)
        assert dut.spawn is not None
        assert dut.spawn.maxread == 1024
        fd_master = os.fdopen(self.master, 'wb')
        try:
            # Test expect string success
            fd_master.write(b'a' * 1024 + b'b' * 1024)
            fd_master.flush()
            time.sleep(0.1)
            # Test expect string maxread
            match1 = dut.expect(re.compile(r'.+', re.DOTALL), timeout=0)
            assert match1
            assert match1.group(0) == 'a' * 1024
            match2 = dut.expect(re.compile(r'.+', re.DOTALL), timeout=0)
            assert match2
            assert match2.group(0) == 'b' * 1024
            # Test expect string failure
            with pytest.raises(Exception):
                dut.expect('aaa', timeout=0.1)
            # Test expect out of buffer
            fd_master.write(b'a' * 1024 + b'b' * 1024)
            fd_master.flush()
            time.sleep(0.1)
            # Known Issue: pexpect can fail due to buffer ``maxread`` limit when timeout is 0.
            with pytest.raises(Exception):
                dut.expect(re.compile(r'.+bbb', re.DOTALL), timeout=0)
            data_cache = dut.data_cache
            assert len(data_cache) == 2048
            assert data_cache == 'a' * 1024 + 'b' * 1024  # data cache is str
            # pexpect can return data
            match3 = dut.expect(re.compile(r'.+?bbb', re.DOTALL), timeout=0.1)
            assert match3
            assert len(match3.group(0)) == 1024 + 3
            assert match3.group(0) == 'a' * 1024 + 'bbb'
            # Test read all data, not limited by buffer ``maxread``
            dut.flush_data()
            fd_master.write(b'a' * 2048 + b'b' * 2048)
            fd_master.flush()
            time.sleep(0.1)
            bytes_cache = dut.read_all_bytes(flush=False)
            assert len(bytes_cache) == 4096
            bytes_cache = dut.read_all_bytes(flush=True)
            assert len(bytes_cache) == 4096
            bytes_cache = dut.read_all_bytes(flush=True)
            assert len(bytes_cache) == 0
            # Test expect out of buffer
            fd_master.write(b'a' * 1024 + b'b' * 1024 + b'ccc')
            fd_master.flush()
            time.sleep(0.1)
            # Test expect endl
            match3 = dut.expect(re.compile(r'.+ccc', re.DOTALL), timeout=0.1)
            assert match3
            assert match3.group(0) == 'a' * 1024 + 'b' * 1024 + 'ccc'
        finally:
            dut.close()
            self._close_file_io(fd_master)
        # Check Total time, All expect should block no more than one seconds other than the failure one
        assert time.perf_counter() - t0 < 2

    def test_serial_dut_data_cache_trim_on_overflow(self) -> None:
        """When the internal data cache grows beyond ``2 * DATA_CACHE_SIZE_LIMIT``,
        the older half must be discarded, keeping only the most recent
        ``DATA_CACHE_SIZE_LIMIT`` bytes.
        """
        ser_read_timeout = 0.003
        ser = serial.Serial(self.serial_port, 115200, timeout=ser_read_timeout)
        dut = SerialDut(ser, 'MyDut', maxread=1024)
        fd_master = os.fdopen(self.master, 'wb')
        original_limit = g.DATA_CACHE_SIZE_LIMIT
        try:
            # Shrink the cache limit so we can trigger the trim path deterministically.
            g.DATA_CACHE_SIZE_LIMIT = 2 * 1024
            # Write more than 2x the limit: head (older) + marker + tail (newer)
            head = b'H' * (1 * 1024)
            marker = b'MARKER'
            tail = b'T' * (6 * 1024)
            fd_master.write(head + marker + tail)
            fd_master.flush()
            time.sleep(ser_read_timeout * 5)
            # Trigger read_nonblocking so the trim branch in PortSpawn runs
            assert dut.spawn is not None
            dut.spawn.read_nonblocking(size=1, timeout=0)  # trigger data cache trim
            # After trim, data cache should be <= DATA_CACHE_SIZE_LIMIT
            assert len(dut.spawn._data_cache) <= 2 * g.DATA_CACHE_SIZE_LIMIT  # pylint: disable=protected-access
            # The oldest bytes must be gone, the newest bytes must remain
            assert dut.spawn._data_cache.endswith(b'T' * 64)  # pylint: disable=protected-access
            assert b'H' * 64 not in dut.spawn._data_cache  # pylint: disable=protected-access
            dut.flush_data()
            assert dut.spawn._data_cache == b''
            # Test via expect()
            data = b'a' * 2048 + b'b' * 2048 + b'c' * 1024
            fd_master.write(data)
            fd_master.flush()
            time.sleep(ser_read_timeout * 5)
            match = dut.expect(re.compile(r'.+', re.DOTALL), timeout=0.1)
            assert match
            assert len(match.group(0)) == 1024  # due to matched and maxread
            assert match.group(0) == 'b' * 1024
            match2 = dut.expect(re.compile(r'.+', re.DOTALL), timeout=0.1)
            assert match2
            assert match2.group(0) == 'c' * 1024  # data_cache cleared at the first time
            dut.flush_data()
            # Test via expect() not match
            data = b'a' * 2048 + b'b' * 2048 + b'c' * 1024
            fd_master.write(data)
            fd_master.flush()
            time.sleep(ser_read_timeout * 3)
            # assert dut.data_cache == 'b' * 1024 + 'c' * 1024
            with pytest.raises(Exception):
                # data cache was cleaned, left b*1024 and c*1024 in pexpect buffer
                dut.expect(re.compile(r'.+aaa', re.DOTALL), timeout=0.1)
            assert len(dut.spawn._data_cache) == 0  # p expect read all data
            assert dut.data_cache == 'b' * 1024 + 'c' * 1024
            # 'b'*1024 in pexpect buffer, c*1024 in port data cache
            data = b'd' * (6 * 1024)  # could trigger data cache trim again
            fd_master.write(data)
            fd_master.write(data)
            fd_master.flush()
            time.sleep(ser_read_timeout * 3)
            data_cache = dut.data_cache
            assert data_cache == 'b' * 1024 + 'c' * 1024 + 'd' * 2048

        finally:
            g.DATA_CACHE_SIZE_LIMIT = original_limit
            dut.close()
            self._close_file_io(fd_master)

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
            bytes_cache = dut.read_all_bytes(flush=True)
            assert bytes_cache == b'ccc'
            # Test read all bytes very long data
            fd_master.write(b'a' * 1000 * 1000)
            fd_master.flush()
            time.sleep(ser_read_timeout * 2)
            bytes_cache = dut.read_all_bytes(flush=False)
            assert len(bytes_cache) == 1000 * 1000
            bytes_cache = dut.read_all_bytes(flush=True)
            assert len(bytes_cache) == 1000 * 1000
            bytes_cache = dut.read_all_bytes(flush=True)
            assert bytes_cache == b''
        finally:
            dut.close()
            self._close_file_io(fd_master)

    def test_serial_dut_log(self) -> None:
        ser_read_timeout = 0.01
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

    def test_expect_timeout_data_in_buffer(self) -> None:
        ser_read_timeout = 0.001
        ser = serial.Serial(self.serial_port, 115200, timeout=ser_read_timeout)
        dut = SerialDut(ser, 'MyDut')
        fd_master = os.fdopen(self.master, 'wb')
        try:
            # port data
            fd_master.write(b'aaabbb')
            fd_master.flush()
            with pytest.raises(ExpectTimeout) as e:
                dut.expect('ddd', timeout=0.01)
            assert e.value.data_in_buffer == b'aaabbb'
            fd_master.write(b'\xff')
            fd_master.flush()
            with pytest.raises(ExpectTimeout) as e:
                dut.expect('ddd', timeout=0.01)
            assert e.value.data_in_buffer == b'aaabbb\xff'
        finally:
            dut.close()
            self._close_file_io(fd_master)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows only test')
class TestSerialDutWin32(unittest.TestCase):
    def setUp(self) -> None:
        self.serial_port = 'loop://'
        self.dut_obj: Optional[serial.SerialBase] = None

    def tearDown(self) -> None:
        if self.dut_obj:
            self.dut_obj.close()

    def test_serial_dut_expect(self) -> None:
        self.dut_obj = serial.serial_for_url(self.serial_port, 115200, timeout=0.001)
        ser = self.dut_obj
        fd_master = ser
        assert fd_master
        dut = SerialDut(ser, 'MyDut')
        t0 = time.perf_counter()
        try:
            # Test expect bytes success
            fd_master.write(b'ccc')
            dut.expect(b'ccc', timeout=1)
            # Test expect regex
            fd_master.write(b'START,regex_value,END')
            match1 = dut.expect(re.compile(r'START,(\w+),END'), timeout=1)
            assert match1
            assert match1.group(1) == 'regex_value'
            # Test expect regex with bytes
            fd_master.write(b'START,regex_value2,END')
            match2 = dut.expect(re.compile(rb'START,(\w+),END'), timeout=1)
            assert match2
            assert match2.group(1) == b'regex_value2'
            # Test expect read all output dat
            # Test regex flags
            fd_master.write(b'data1 data1 data1 \r\n')
            time.sleep(0.1)
            fd_master.write(b'data2 data2 data2')
            time.sleep(0.1)
            match3 = dut.expect(re.compile(r'.+', re.DOTALL), timeout=0)
            assert match3
            assert match3.group(0) == 'data1 data1 data1 \r\ndata2 data2 data2'
            # Test expect more than one match
            # Hop to got match twice
            fd_master.write(b'match1, match2\n')
            time.sleep(0.1)
            match4 = dut.expect(re.compile(r'(match1|match2)', re.DOTALL), timeout=0)
            assert match4
            assert match4.group(0) == 'match1'
            match5 = dut.expect(re.compile(r'(match1|match2)', re.DOTALL), timeout=0)
            assert match5
            assert match5.group(0) == 'match2'
        finally:
            dut.close()
        # Check Total time, All expect should block no more than one seconds other than the failure one
        assert time.perf_counter() - t0 < 2


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
