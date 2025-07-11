import random
import string
from datetime import datetime
from unittest import mock

import pytest

from esptest.common.encoding import to_bytes, to_str
from esptest.common.generator import get_next_index
from esptest.common.timestamp import timestamp_slug, timestamp_str


@mock.patch('esptest.common.timestamp.datetime')
def test_timestamp(patch_datetime: mock.Mock) -> None:
    patch_datetime.now.return_value = datetime(2025, 7, 1, 10, 1, 2, 100)
    s = timestamp_str()
    assert s == '2025-07-01 10:01:02.000100'
    s = timestamp_slug()
    assert s == '2025-07-01__10-01-02_000100'


def test_get_next_index() -> None:
    magic = ''.join(random.choices(string.ascii_letters, k=10))
    index = get_next_index(f'{magic}_01')
    assert index == 1
    index = get_next_index(f'{magic}_01')
    assert index == 2
    index = get_next_index(f'{magic}_02')
    assert index == 1
    index = get_next_index(f'{magic}_01')
    assert index == 3


def test_to_str_to_bytes() -> None:
    # to str
    bytes_data = b'abcd123\r\n'
    assert to_str(bytes_data) == 'abcd123\r\n'
    # to bytes
    data = '123456ABC'
    assert to_bytes(data) == b'123456ABC'
    data = '中文'
    assert to_bytes(data) == b'\xe4\xb8\xad\xe6\x96\x87'
    assert to_str(b'\xe4\xb8\xad\xe6\x96\x87') == '中文'
    # to_str with invalid chars
    bytes_data = b'\xff\xff'
    res = to_str(bytes_data)
    assert res == '��'
    assert to_bytes(res) == b'\xef\xbf\xbd\xef\xbf\xbd'


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
