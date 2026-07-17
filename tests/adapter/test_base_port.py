import threading
import time

import pytest

from esptest.adapter.port.base_port import BasePort, RawPort
from esptest.common.data_monitor import DataMonitor
from esptest.config.global_config import g


class MockRawPort(RawPort):
    def __init__(self) -> None:
        self._data = bytearray()
        self._lock = threading.Lock()
        self._closed = False
        self.written = bytearray()

    def write_bytes(self, data: bytes) -> None:
        with self._lock:
            self.written.extend(data)

    def read_bytes(self, timeout: float = 0) -> bytes:
        deadline = time.time() + max(timeout, 0)
        while time.time() <= deadline:
            with self._lock:
                if self._data:
                    data = bytes(self._data)
                    self._data.clear()
                    return data
                if self._closed:
                    return b''
            time.sleep(0.001)
        return b''

    def feed_data(self, data: bytes) -> None:
        with self._lock:
            self._data.extend(data)

    def close(self) -> None:
        with self._lock:
            self._closed = True


class MockReconnectRawPort(RawPort):
    def __init__(self, error_message: str) -> None:
        self.error_message = error_message
        self._data = bytearray()
        self._lock = threading.Lock()
        self._raise_once = True
        self._is_open = True
        self.open_called_count = 0
        self.close_called_count = 0

    def write_bytes(self, data: bytes) -> None:
        return None

    def read_bytes(self, timeout: float = 0) -> bytes:
        if self._raise_once:
            self._raise_once = False
            raise Exception(self.error_message)
        deadline = time.time() + max(timeout, 0)
        while time.time() <= deadline:
            with self._lock:
                if self._is_open and self._data:
                    data = bytes(self._data)
                    self._data.clear()
                    return data
            time.sleep(0.001)
        return b''

    def feed_data(self, data: bytes) -> None:
        with self._lock:
            self._data.extend(data)

    def close(self) -> None:
        with self._lock:
            self._is_open = False
            self.close_called_count += 1

    def open(self) -> None:
        with self._lock:
            self._is_open = True
            self.open_called_count += 1


def test_base_port_rx_log_callback_and_monitor_with_mock_raw_port() -> None:
    received_data = []

    def rx_log_callback(port_name: str, data: bytes) -> None:
        received_data.append((port_name, data))

    monitor = DataMonitor('hello_rx_monitor')
    raw_port = MockRawPort()
    port = BasePort(raw_port, name='mock_port', rx_log_callback=rx_log_callback, monitors=[monitor])
    try:
        raw_port.feed_data(b'hello_rx_monitor')

        timeout = time.time() + 1
        while time.time() < timeout:
            if received_data and monitor.matched_count >= 1:
                break
            time.sleep(0.01)

        assert received_data
        assert received_data[-1][0] == 'mock_port'
        assert b'hello_rx_monitor' in received_data[-1][1]
        assert monitor.matched_count >= 1
        assert monitor.matched_ports[-1] == 'mock_port'
    finally:
        port.close()


def test_serial_error_with_zero_reconnect_count_should_not_reconnect(monkeypatch) -> None:  # type: ignore
    monkeypatch.setattr(g, 'ALLOW_SERIAL_ERROR_RECONNECT_COUNT', 0)
    raw_port = MockReconnectRawPort('GetOverlappedResult failed (PermissionError(13, "拒绝访问。", None, 5))')
    port = BasePort(raw_port, name='mock_port_no_reconnect')
    try:
        assert port.spawn is not None
        timeout = time.time() + 1
        while time.time() < timeout:
            if not port.spawn._read_thread.is_alive():  # pylint: disable=protected-access
                break
            time.sleep(0.01)
        assert not port.spawn._read_thread.is_alive()  # pylint: disable=protected-access
        assert raw_port.open_called_count == 0
        assert raw_port.close_called_count == 0
    finally:
        port.close()


def test_serial_error_with_reconnect_count_should_reconnect(monkeypatch) -> None:  # type: ignore
    monkeypatch.setattr(g, 'ALLOW_SERIAL_ERROR_RECONNECT_COUNT', 1)
    received_data = []
    raw_port = MockReconnectRawPort('GetOverlappedResult failed (PermissionError(13, "拒绝访问。", None, 5))')
    port = BasePort(
        raw_port,
        name='mock_port_reconnect',
        rx_log_callback=lambda port_name, data: received_data.append((port_name, data)),
    )
    try:
        assert port.spawn is not None
        timeout = time.time() + 1
        while time.time() < timeout:
            if raw_port.open_called_count > 0:
                break
            time.sleep(0.01)
        assert raw_port.open_called_count > 0
        assert raw_port.close_called_count > 0

        raw_port.feed_data(b'hello_after_reconnect')
        timeout = time.time() + 1
        while time.time() < timeout:
            # first data should be reconnect message
            if len(received_data) == 2:
                break
            time.sleep(0.01)
        assert received_data
        assert received_data[-1][0] == 'mock_port_reconnect'
        assert b'hello_after_reconnect' in received_data[-1][1]
        assert port.spawn._read_thread.is_alive()  # pylint: disable=protected-access
    finally:
        port.close()


def test_base_port_change_serial_config_not_available() -> None:
    raw_port = MockRawPort()
    port = BasePort(raw_port, name='no_serial_cfg')
    try:
        with pytest.raises(OSError, match='change_serial_config is not available'):
            port.change_serial_config(baudrate=115200)
    finally:
        port.close()


def test_base_port_write_expect_raise_when_redirect_thread_stopped() -> None:
    raw_port = MockRawPort()
    port = BasePort(raw_port, name='stopped_port')
    try:
        assert port.stop_redirect_thread() is True
        with pytest.raises(OSError, match='redirect thread not started'):
            port.write('x')
        with pytest.raises(OSError, match='redirect thread not started'):
            port.expect('x', timeout=0.01)
        with pytest.raises(OSError, match='redirect thread not started'):
            port.expect_exact('x', timeout=0.01)
    finally:
        port.close()


def test_base_port_expect_exact_succeeds_when_pattern_matches() -> None:
    raw_port = MockRawPort()
    port = BasePort(raw_port, name='expect_exact_ok')
    try:
        raw_port.feed_data(b'hello world\n')
        port.expect_exact('hello world', timeout=2)
    finally:
        port.close()


def test_base_port_disable_redirect_thread_restores_after_exception() -> None:
    """Flash/download failures must not leave redirect thread permanently stopped."""
    raw_port = MockRawPort()
    port = BasePort(raw_port, name='restore_after_exc')
    try:
        assert port.spawn is not None
        with pytest.raises(RuntimeError, match='download failed'):
            with port.disable_redirect_thread():
                assert port.spawn is None
                raise RuntimeError('download failed')
        assert port.spawn is not None
        raw_port.feed_data(b'hello after restore\n')
        port.expect_exact('hello after restore', timeout=2)
    finally:
        port.close()
