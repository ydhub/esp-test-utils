import logging
import os
import sys
import urllib.request


def _progress(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
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


def download_file(url: str, local_filename: str, progress: bool = True) -> None:
    """
    Download a file from a URL.

    Args:
        url: The URL of the file to download.
        local_filename: The local filename to save the downloaded file.
        progress: Whether to show the download progress.
    """
    if os.path.exists(local_filename):
        os.remove(local_filename)
    try:
        if progress:
            logging.info(f'Downloading {url} -> {local_filename}')
            urllib.request.urlretrieve(url, local_filename, reporthook=_progress)
            sys.stdout.write('\n')
            logging.info('Download complete!')
        else:
            urllib.request.urlretrieve(url, local_filename)
    except OSError as e:
        logging.error(f'Download {url} failed: {str(e)}')
