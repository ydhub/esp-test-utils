from typing import Optional

from esptest.adapter.port.port_log import HtmlLogFormatter, PortLogFormatter, PortLogWriter, RawLogFormatter

IDLE = 0.05
TS = b'\n[TS]\n'


def _writer(formatter: Optional[PortLogFormatter] = None) -> PortLogWriter:
    return PortLogWriter(idle_timeout=IDLE, timestamp_fn=lambda: 'TS', now=0.0, formatter=formatter)


def test_feed_complete_line_starts_timestamp_block() -> None:
    writer = _writer()
    assert writer.feed(b'data\n', now=1.0) == TS + b'data\n'


def test_feed_idle_then_fragment_then_rest_of_line_same_block() -> None:
    writer = _writer()
    out = writer.feed(b'data\n', now=1.0)
    out += writer.feed(b'', now=1.0 + IDLE + 0.01)
    out += writer.feed(b'aaa', now=1.0 + IDLE + 0.01)
    assert out.endswith(b'aaa')
    out += writer.feed(b'bbb\n', now=1.0 + IDLE + 0.02)
    assert out.endswith(b'aaabbb\n')
    assert out.count(b'\n[') == 2


def test_feed_idle_between_fragments_starts_new_timestamp() -> None:
    writer = _writer()
    out = writer.feed(b'data\n', now=1.0)
    out += writer.feed(b'', now=2.0)
    out += writer.feed(b'aaa', now=2.0)
    out += writer.feed(b'', now=3.0)
    out += writer.feed(b'bbb\n', now=3.0)
    assert b'aaabbb' not in out
    assert b'aaa\n[' in out
    assert out.endswith(b'bbb\n')
    assert out.count(b'\n[') == 3


def test_feed_contiguous_fragment_flushes_into_same_block() -> None:
    writer = _writer()
    out = writer.feed(b'data\n', now=1.0)
    assert writer.feed(b'aaa', now=1.001) == b''
    out += writer.feed(b'', now=1.0 + IDLE + 0.01)
    assert out.endswith(b'data\naaa')
    assert out.count(b'\n[') == 1
    out += writer.feed(b'bbb\n', now=1.0 + IDLE + 0.02)
    assert b'data\naaa\n[' in out
    assert out.endswith(b'bbb\n')
    assert out.count(b'\n[') == 2


def test_reset_starts_a_new_block() -> None:
    writer = _writer()
    writer.feed(b'data\n', now=1.0)
    writer.reset(now=0.0)
    assert writer.feed(b'next\n', now=1.001) == TS + b'next\n'


def test_raw_formatter_omits_timestamps() -> None:
    writer = _writer(RawLogFormatter())
    out = writer.feed(b'data\n', now=1.0)
    out += writer.feed(b'aaa', now=1.001)
    out += writer.feed(b'', now=1.0 + IDLE + 0.01)
    out += writer.feed(b'bbb\n', now=1.0 + IDLE + 0.02)
    # Idle does not insert a newline; raw output is the serial bytes in order.
    assert b'[TS]' not in out


def test_html_formatter_wraps_blocks_and_escapes_payload() -> None:
    writer = _writer(HtmlLogFormatter())
    out = writer.feed(b'data\n', now=1.0)
    out += writer.feed(b'<x>', now=1.001)
    out += writer.feed(b'', now=1.0 + IDLE + 0.01)
    out += writer.feed(b'bbb\n', now=1.0 + IDLE + 0.02)
    text = out.decode('utf-8')
    assert '<time>TS</time>' in text
    assert text.count('<time>TS</time>') == 2
    assert '&lt;x&gt;' in text
    assert '<x>' not in text
    assert writer.formatter.end().decode('utf-8').endswith('</pre>\n')
