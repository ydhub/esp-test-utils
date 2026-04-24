import threading
import time

from esptest.adapter.port.base_port import BasePort, RawPort
from esptest.common.data_monitor import DataMonitor


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
