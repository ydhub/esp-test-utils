import re
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

import esptest.common.timestamp as timestamp_module
from esptest.common.timestamp import (
    parse_timestamp,
    timestamp_iso,
    timestamp_slug,
    timestamp_str,
)

CST = timezone(timedelta(hours=8))


def test_timestamp_str_default_uses_iso_t_separator() -> None:
    with mock.patch.object(timestamp_module, 'datetime') as patch_datetime:
        patch_datetime.now.return_value = datetime(2025, 7, 1, 10, 1, 2, 100)
        assert timestamp_str() == '2025-07-01T10:01:02.000100'


def test_timestamp_str_accepts_custom_format() -> None:
    dt = datetime(2025, 7, 1, 10, 1, 2, tzinfo=CST)
    assert timestamp_str(fmt='%Y/%m/%d', dt=dt) == '2025/07/01'


def test_timestamp_str_keeps_existing_timezone() -> None:
    dt = datetime(2025, 7, 1, 10, 1, 2, 100, tzinfo=CST)
    assert timestamp_str(fmt='%Y-%m-%dT%H:%M:%S.%f%z', dt=dt) == '2025-07-01T10:01:02.000100+0800'


def test_timestamp_iso_includes_offset_for_aware_dt() -> None:
    dt = datetime(2025, 7, 1, 10, 1, 2, 100, tzinfo=CST)
    assert timestamp_iso(dt) == '2025-07-01T10:01:02.000100+0800'


def test_timestamp_iso_attaches_local_offset_for_naive_dt() -> None:
    dt = datetime(2025, 7, 1, 10, 1, 2, 100)
    result = timestamp_iso(dt)
    # The offset depends on the machine's local timezone, so only assert shape.
    assert re.match(r'^2025-07-01T10:01:02\.000100[+-]\d{4}$', result)


def test_timestamp_slug_replaces_separators() -> None:
    dt = datetime(2025, 7, 1, 10, 1, 2, 100)
    assert timestamp_slug(dt=dt) == '2025-07-01T10-01-02_000100'


@pytest.mark.parametrize(
    'text, expected',
    [
        ('2025-07-01T10:01:02.000100', datetime(2025, 7, 1, 10, 1, 2, 100)),
        ('2025-07-01T10:01:02', datetime(2025, 7, 1, 10, 1, 2)),
        ('2025-07-01 10:01:02.000100', datetime(2025, 7, 1, 10, 1, 2, 100)),
        ('2025-07-01 10:01:02', datetime(2025, 7, 1, 10, 1, 2)),
    ],
)
def test_parse_timestamp_auto_detects_naive_formats(text: str, expected: datetime) -> None:
    assert parse_timestamp(text) == expected


@pytest.mark.parametrize(
    'text',
    [
        '2025-07-01T10:01:02.000100+0800',
        '2025-07-01T10:01:02.000100+08:00',
        '2025-07-01T10:01:02+0800',
        '2025-07-01 10:01:02+0800',
    ],
)
def test_parse_timestamp_preserves_timezone(text: str) -> None:
    result = parse_timestamp(text)
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(hours=8)


def test_parse_timestamp_handles_z_suffix() -> None:
    result = parse_timestamp('2025-07-01T10:01:02Z')
    assert result.utcoffset() == timedelta(0)


def test_parse_timestamp_round_trips_timestamp_iso() -> None:
    dt = datetime(2025, 7, 1, 10, 1, 2, 100, tzinfo=CST)
    assert parse_timestamp(timestamp_iso(dt)) == dt


def test_parse_timestamp_uses_explicit_format() -> None:
    assert parse_timestamp('01/07/2025', fmt='%d/%m/%Y') == datetime(2025, 7, 1)


def test_parse_timestamp_explicit_format_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        parse_timestamp('2025-07-01', fmt='%d/%m/%Y')


def test_parse_timestamp_rejects_unknown_format() -> None:
    with pytest.raises(ValueError):
        parse_timestamp('not-a-timestamp')


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
