"""Timestamped serial log writer: line cache, idle flush, and timestamp blocks."""

import time

import esptest.common.compat_typing as t

from ...common import timestamp_str

# Incomplete fragments flush after this many read timeouts of silence.
IDLE_TIMEOUT_MULTIPLIER = 5


class PortLogWriter:
    """Turn a byte stream into timestamped log chunks.

    Call ``feed(data)`` with each read (use ``b''`` for an idle check). Returns
    bytes that should be appended to the log file now, including an optional
    ``\\n[<time>]\\n`` header when a new timestamp block starts.
    """

    def __init__(
        self,
        idle_timeout: float,
        timestamp_fn: t.Optional[t.Callable[[], str]] = None,
        now: t.Optional[float] = None,
    ) -> None:
        self.idle_timeout = idle_timeout
        self._timestamp_fn = timestamp_fn or timestamp_str
        self._line_cache = b''
        self._log_line_open = False
        self._log_block_open = False
        self._last_write_log_time = time.time() if now is None else now

    def reset(self, now: t.Optional[float] = None) -> None:
        self._line_cache = b''
        self._log_line_open = False
        self._log_block_open = False
        self._last_write_log_time = time.time() if now is None else now

    def feed(self, data: bytes, now: t.Optional[float] = None) -> bytes:
        """Consume serial bytes (or an idle tick) and return log bytes to write."""
        if now is None:
            now = time.time()
        idle = now - self._last_write_log_time > self.idle_timeout
        out = b''
        if idle:
            if self._line_cache:
                out += self._emit(self._line_cache, now)
                self._line_cache = b''
            self._log_block_open = False

        if not data:
            return out

        self._line_cache += data
        data_to_write = b''
        if b'\n' in self._line_cache:
            _index = self._line_cache.rfind(b'\n') + 1
            data_to_write = self._line_cache[:_index]
            self._line_cache = self._line_cache[_index:]
        if not data_to_write and self._line_cache and (idle or self._log_line_open):
            data_to_write = self._line_cache
            self._line_cache = b''
        out += self._emit(data_to_write, now)
        return out

    def _emit(self, data_to_write: bytes, now: float) -> bytes:
        if not data_to_write:
            return b''
        header = b''
        if not self._log_block_open:
            header = f'\n[{self._timestamp_fn()}]\n'.encode()
        self._last_write_log_time = now
        self._log_line_open = not data_to_write.endswith(b'\n')
        self._log_block_open = True
        return header + data_to_write
