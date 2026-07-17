import urllib.error
from pathlib import Path

import pytest

import esptest.common.fs as fs
from esptest.common.fs import get_file_bytes, get_file_text


def test_get_file_text_local(tmp_path: Path) -> None:
    path = tmp_path / 'sample.txt'
    path.write_text('hello\n中文', encoding='utf-8')
    assert get_file_text(str(path)) == 'hello\n中文'
    assert get_file_text(str(path)) == path.read_text(encoding='utf-8')


def test_get_file_text_local_crlf_like_read_text(tmp_path: Path) -> None:
    path = tmp_path / 'crlf.txt'
    path.write_bytes(b'hello\r\nworld')
    assert get_file_text(str(path)) == 'hello\nworld'
    assert get_file_text(str(path)) == path.read_text(encoding='utf-8')


def test_get_file_bytes_local(tmp_path: Path) -> None:
    path = tmp_path / 'sample.bin'
    path.write_bytes(b'\xff\xfe\x00')
    assert get_file_bytes(str(path)) == b'\xff\xfe\x00'


def test_get_file_text_local_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        get_file_text(str(tmp_path / 'missing.txt'))


def test_non_http_prefix_is_local_path(tmp_path: Path) -> None:
    # Path merely containing "http" must not be treated as URL
    path = tmp_path / 'http_backup.txt'
    path.write_text('local', encoding='utf-8')
    assert get_file_text(str(path)) == 'local'


def test_get_file_bytes_http_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b'remote-bytes'

    class FakeResponse:
        def read(self) -> bytes:
            return payload

        def __enter__(self) -> 'FakeResponse':
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(url: str, timeout: object = None) -> FakeResponse:
        assert url == 'https://example.com/a.bin'
        return FakeResponse()

    monkeypatch.setattr(fs.urllib.request, 'urlopen', fake_urlopen)
    assert get_file_bytes('https://example.com/a.bin') == payload


def test_get_file_text_http_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def read(self) -> bytes:
            return 'remote-text'.encode('utf-8')

        def __enter__(self) -> 'FakeResponse':
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        fs.urllib.request,
        'urlopen',
        lambda url, timeout=None: FakeResponse(),
    )
    assert get_file_text('http://example.com/a.txt') == 'remote-text'


def test_get_file_bytes_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(url: str, timeout: object = None) -> None:
        raise urllib.error.URLError('network down')

    monkeypatch.setattr(fs.urllib.request, 'urlopen', fake_urlopen)
    with pytest.raises(urllib.error.URLError):
        get_file_bytes('https://example.com/missing')


def test_common_package_exports() -> None:
    from esptest.common import get_file_bytes as exported_bytes
    from esptest.common import get_file_text as exported_text

    assert callable(exported_bytes) and callable(exported_text)
