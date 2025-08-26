import io
import os
import socket
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from esptest.tools.http_download import download_file

TEST_DOWNLOAD_FILE_URL = os.getenv('TEST_DOWNLOAD_FILE_URL', 'https://ci.espressif.cn:42348/cache/qa-test/pytest/1.txt')
TEST_DOWNLOAD_FILE_NAME = os.getenv('TEST_DOWNLOAD_FILE_NAME', '1.txt')
TEST_DOWNLOAD_FILE_SIZE = os.getenv('TEST_DOWNLOAD_FILE_SIZE', '57')


def fake_create_connection(*args, **kwargs):  # type: ignore
    raise socket.timeout('timed out')


def test_download_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_name = tmp_path / TEST_DOWNLOAD_FILE_NAME
    download_file(TEST_DOWNLOAD_FILE_URL, str(file_name), progress=False)
    assert file_name.is_file()
    assert file_name.stat().st_size == int(TEST_DOWNLOAD_FILE_SIZE)
    file_name.unlink()
    assert not file_name.is_file()
    with redirect_stdout(io.StringIO()) as stdout:
        download_file(TEST_DOWNLOAD_FILE_URL, str(file_name), progress=True)
        assert '100.0%' in stdout.getvalue()
    assert file_name.is_file()
    assert file_name.stat().st_size == int(TEST_DOWNLOAD_FILE_SIZE)

    # invalid url
    invalid_download_url = 'https://invalid-url.invalid/invalid-file'
    invalid_file_name = tmp_path / 'invalid-file'
    with pytest.raises(OSError):
        download_file(invalid_download_url, str(invalid_file_name), progress=True)

    # downlad with timeout
    monkeypatch.setattr(socket, 'create_connection', fake_create_connection)
    fake_url = 'http://example.com/fake.bin'
    fake_file_name = tmp_path / 'fake.bin'
    with pytest.raises(OSError):  # urllib.error.URLError
        download_file(fake_url, str(fake_file_name), timeout=0.01, progress=True)
