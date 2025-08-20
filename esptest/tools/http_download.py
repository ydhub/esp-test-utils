import logging
import os
import sys
import urllib.request
from typing import Optional


def _progress(downloaded: int, total_size: int) -> None:
    if total_size > 0:
        percent = min(downloaded / total_size * 100, 100)
        bar_len = 50
        filled_len = int(bar_len * downloaded // total_size)
        progress_bar = '█' * filled_len + '-' * (bar_len - filled_len)
        sys.stdout.write(f'\r[{progress_bar}] {percent:6.1f}%')
        sys.stdout.flush()
    else:
        # show downloaded size if no total_size
        sys.stdout.write(f'\rDownloaded {downloaded} bytes')
        sys.stdout.flush()


def download_file(url: str, local_filename: str, timeout: Optional[float] = None, progress: bool = True) -> None:
    """
    Download a file from a URL.

    The optional *timeout* parameter specifies a timeout in seconds for
    blocking operations like the connection attempt (if not specified, the
    global default timeout setting will be used). This only works for HTTP,
    HTTPS and FTP connections.

    Args:
        url: The URL of the file to download.
        local_filename: The local filename to save the downloaded file.
        progress: Whether to show the download progress.
    """
    if os.path.exists(local_filename):
        os.remove(local_filename)
    try:
        logging.info(f'Downloading {url} -> {local_filename}')
        with urllib.request.urlopen(url, timeout=timeout) as response, open(local_filename, 'wb') as out_file:
            total_length = int(response.getheader('Content-Length') or '0')
            downloaded = 0
            block_size = 8192
            while True:
                chunk = response.read(block_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                if progress:
                    _progress(downloaded, total_length)
            if progress:
                sys.stdout.write('\n')
                sys.stdout.flush()
            if total_length and total_length != downloaded:
                logging.error(f'Download {url} failed! maybe url timeout.')
                raise OSError(f'Download {url} failed: total_length {total_length} != downloaded {downloaded}')
        logging.info('Download complete!')
    except OSError as e:
        logging.error(f'Download {url} failed: {str(e)}')
        raise e
