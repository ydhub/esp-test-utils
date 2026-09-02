"""Serial log writer: line cache, idle flush, and pluggable output formats."""

import html
import time

import esptest.common.compat_typing as t

from ...common import timestamp_str

# Incomplete fragments flush after this many read timeouts of silence.
IDLE_TIMEOUT_MULTIPLIER = 5


class PortLogFormatter:
    """Render one flushed payload. Subclass to add raw / HTML (or other) sinks."""

    def format_chunk(self, payload: bytes, new_block: bool, time_label: str) -> bytes:
        """Return bytes to append for ``payload``.

        ``new_block`` is True when this chunk starts a new idle-separated burst.
        ``time_label`` is the timestamp string for that burst.
        """
        raise NotImplementedError

    def begin(self) -> bytes:
        """Optional file header (HTML document, etc.)."""
        return b''

    def end(self) -> bytes:
        """Optional file footer."""
        return b''

    def reset(self) -> None:
        """Clear formatter-only state (open HTML tags, etc.)."""
        return


class TimestampedLogFormatter(PortLogFormatter):
    """Default DUT log: ``\\n[<time>]\\n`` then payload for each new block."""

    def format_chunk(self, payload: bytes, new_block: bool, time_label: str) -> bytes:
        if not new_block:
            return payload
        return f'\n[{time_label}]\n'.encode() + payload


class RawLogFormatter(PortLogFormatter):
    """Serial bytes only, no timestamps. For a parallel .raw log later."""

    def format_chunk(self, payload: bytes, new_block: bool, time_label: str) -> bytes:
        return payload


class HtmlLogFormatter(PortLogFormatter):
    """Reserved HTML log: ``<time>`` per burst, payload in ``<pre>`` (escaped)."""

    def __init__(self) -> None:
        self._block_open = False

    def reset(self) -> None:
        self._block_open = False

    def format_chunk(self, payload: bytes, new_block: bool, time_label: str) -> bytes:
        out = b''
        if new_block:
            if self._block_open:
                out += b'</pre>\n'
            out += f'<time>{html.escape(time_label, quote=True)}</time><pre>'.encode()
            self._block_open = True
        out += html.escape(payload.decode('utf-8', 'replace'), quote=False).encode()
        return out

    def end(self) -> bytes:
        if not self._block_open:
            return b''
        return b'</pre>\n'


class PortLogWriter:
    """Turn a byte stream into log chunks.

    Call ``feed(data)`` with each read (use ``b''`` for an idle check). Returns
    bytes that should be appended now, shaped by ``formatter`` (default:
    timestamped text). Swap in :class:`RawLogFormatter` or
    :class:`HtmlLogFormatter` for a parallel raw/HTML file later.
    """

    def __init__(
        self,
        idle_timeout: float,
        timestamp_fn: t.Optional[t.Callable[[], str]] = None,
        now: t.Optional[float] = None,
        formatter: t.Optional[PortLogFormatter] = None,
    ) -> None:
        self.idle_timeout = idle_timeout
        self.formatter = formatter or TimestampedLogFormatter()
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
        self.formatter.reset()

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
        new_block = not self._log_block_open
        time_label = self._timestamp_fn() if new_block else ''
        chunk = self.formatter.format_chunk(data_to_write, new_block, time_label)
        self._last_write_log_time = now
        self._log_line_open = not data_to_write.endswith(b'\n')
        self._log_block_open = True
        return chunk
