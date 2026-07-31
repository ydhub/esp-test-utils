import io
import os
import socket
import threading
from contextlib import redirect_stdout
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Tuple
from urllib.parse import urljoin

import pytest

from esptest.tools.http_download import download_dir, download_file, path_matches_whitelist

TEST_DOWNLOAD_FILE_URL = os.getenv('TEST_DOWNLOAD_FILE_URL', 'https://ci.espressif.cn:42348/cache/qa-test/pytest/1.txt')
TEST_DOWNLOAD_FILE_NAME = os.getenv('TEST_DOWNLOAD_FILE_NAME', '1.txt')
TEST_DOWNLOAD_FILE_SIZE = os.getenv('TEST_DOWNLOAD_FILE_SIZE', '57')


def fake_create_connection(*args, **kwargs):  # type: ignore
    raise socket.timeout('timed out')


@pytest.fixture()
def http_dir_server(tmp_path: Path) -> Iterator[Tuple[str, Path]]:
    """Serve an Apache-like autoindex tree via SimpleHTTPRequestHandler."""
    remote = tmp_path / 'remote'
    remote.mkdir()
    (remote / 'ssc.bin').write_bytes(b'ssc')
    (remote / 'skip.elf').write_bytes(b'elf')
    (remote / 'flasher_args.json').write_text('{}', encoding='utf-8')
    bootloader = remote / 'bootloader'
    bootloader.mkdir()
    (bootloader / 'bootloader.bin').write_bytes(b'boot')
    (bootloader / 'bootloader.elf').write_bytes(b'bootelf')
    part = remote / 'partition_table'
    part.mkdir()
    (part / 'partition-table.bin').write_bytes(b'part')

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # type: ignore
            return

    handler = partial(QuietHandler, directory=str(remote))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = 'http://127.0.0.1:%d/' % server.server_address[1]
    try:
        yield base_url, remote
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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


@pytest.mark.parametrize(
    'rel,pattern,expected',
    [
        ('ssc.bin', '*.bin', True),
        ('bootloader/bootloader.bin', '*.bin', False),
        ('bootloader/bootloader.bin', '**/*.bin', True),
        ('bootloader/bootloader.bin', 'bootloader/*', True),
        ('partition_table/partition-table.bin', 'bootloader/*', False),
        ('flasher_args.json', '*.json', True),
        ('skip.elf', '*.bin', False),
    ],
)
def test_path_matches_whitelist(rel: str, pattern: str, expected: bool) -> None:
    assert path_matches_whitelist(rel, [pattern]) is expected


def test_path_matches_whitelist_empty_means_all() -> None:
    assert path_matches_whitelist('anything.elf', None) is True
    assert path_matches_whitelist('anything.elf', []) is True


def test_download_dir_recursive(http_dir_server: Tuple[str, Path], tmp_path: Path) -> None:
    base_url, _remote = http_dir_server
    dest = tmp_path / 'out'
    # URL without trailing slash should still resolve via redirect to directory
    download_dir(base_url.rstrip('/'), str(dest), progress=False)
    assert dest.is_dir()
    assert (dest / 'ssc.bin').read_bytes() == b'ssc'
    assert (dest / 'skip.elf').read_bytes() == b'elf'
    assert (dest / 'flasher_args.json').is_file()
    assert (dest / 'bootloader' / 'bootloader.bin').read_bytes() == b'boot'
    assert (dest / 'bootloader' / 'bootloader.elf').read_bytes() == b'bootelf'
    assert (dest / 'partition_table' / 'partition-table.bin').read_bytes() == b'part'


def test_download_dir_whitelist(http_dir_server: Tuple[str, Path], tmp_path: Path) -> None:
    base_url, _remote = http_dir_server
    dest = tmp_path / 'filtered'
    download_dir(
        base_url,
        str(dest),
        progress=False,
        whitelist=['*.bin', '**/*.bin', '*.json'],
    )
    assert dest.is_dir()
    assert (dest / 'ssc.bin').is_file()
    assert (dest / 'flasher_args.json').is_file()
    assert (dest / 'bootloader' / 'bootloader.bin').is_file()
    assert (dest / 'partition_table' / 'partition-table.bin').is_file()
    assert not (dest / 'skip.elf').exists()
    assert not (dest / 'bootloader' / 'bootloader.elf').exists()


def test_download_dir_ignores_parent_and_query_links(tmp_path: Path) -> None:
    """Synthetic Apache-style index with parent/query/external links."""
    remote = tmp_path / 'remote'
    remote.mkdir()
    (remote / 'keep.bin').write_bytes(b'k')

    html = """<!DOCTYPE HTML>
<html><head><title>Index</title></head><body>
<h1>Index of /pkg/</h1>
<ul>
<li><a href="/">Root</a></li>
<li><a href="../">Parent Directory</a></li>
<li><a href="?C=N;O=D">Name</a></li>
<li><a href="http://evil.example/x.bin">external</a></li>
<li><a href="keep.bin">keep.bin</a></li>
</ul>
</body></html>
"""

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):  # type: ignore
            super().__init__(*args, directory=str(remote), **kwargs)

        def log_message(self, fmt: str, *args) -> None:  # type: ignore
            return

        def list_directory(self, path):  # type: ignore
            body = html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = 'http://127.0.0.1:%d/' % server.server_address[1]
    dest = tmp_path / 'safe'
    try:
        download_dir(base_url, str(dest), progress=False)
        assert (dest / 'keep.bin').read_bytes() == b'k'
        assert not (dest / 'x.bin').exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_download_file_still_saves_single_file(http_dir_server: Tuple[str, Path], tmp_path: Path) -> None:
    base_url, _remote = http_dir_server
    dest = tmp_path / 'ssc.bin'
    download_file(urljoin(base_url, 'ssc.bin'), str(dest), progress=False)
    assert dest.is_file()
    assert dest.read_bytes() == b'ssc'


def test_download_dir_progress_is_compact(http_dir_server: Tuple[str, Path], tmp_path: Path) -> None:
    """Folder downloads should show file-count progress, not one 100% bar per file."""
    base_url, _remote = http_dir_server
    dest = tmp_path / 'out'
    with redirect_stdout(io.StringIO()) as stdout:
        download_dir(base_url, str(dest), progress=True)
    out = stdout.getvalue()
    assert dest.is_dir()
    assert (dest / 'ssc.bin').is_file()
    # No per-file byte bars (those end with "100.0%\\n")
    assert '100.0%' not in out
    assert 'Downloaded' in out and 'files' in out
    # Count progress like "7/7" should appear
    assert '/' in out
