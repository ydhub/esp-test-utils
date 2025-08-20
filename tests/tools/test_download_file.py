import io
import os
from contextlib import redirect_stdout
from pathlib import Path

from esptest.tools.http_download import download_file

TEST_DOWNLOAD_FILE_URL = os.getenv('TEST_DOWNLOAD_FILE_URL', 'https://ci.espressif.cn:42348/cache/qa-test/pytest/1.txt')
TEST_DOWNLOAD_FILE_NAME = os.getenv('TEST_DOWNLOAD_FILE_NAME', '1.txt')
TEST_DOWNLOAD_FILE_SIZE = os.getenv('TEST_DOWNLOAD_FILE_SIZE', '57')


def test_download_file(tmp_path: Path) -> None:
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
