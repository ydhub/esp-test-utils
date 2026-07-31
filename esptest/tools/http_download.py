import fnmatch
import logging
import os
import sys
from html.parser import HTMLParser
from http.client import HTTPResponse
from urllib.error import URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import urlopen

import esptest.common.compat_typing as t

logger = logging.getLogger('http_download')


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


def _folder_progress(done: int, total: int, name: str) -> None:
    """Single-line file-count progress for directory downloads."""
    # Pad/truncate name so the line overwrites cleanly in most terminals.
    display = name if len(name) <= 48 else '...' + name[-45:]
    sys.stdout.write(f'\rDownloading {done}/{total}  {display:<48}')
    sys.stdout.flush()


def path_matches_whitelist(rel_path: str, whitelist: t.Optional[t.Iterable[str]]) -> bool:
    """Return True if *rel_path* should be downloaded under *whitelist*.

    Patterns are glob expressions matched against the path relative to the
    download root (POSIX separators):

    - ``*.bin`` — only files in the root directory
    - ``bootloader/*`` — files directly under ``bootloader/``
    - ``**/*.bin`` — ``.bin`` files at any depth

    ``None`` or an empty whitelist means download everything.
    """
    if not whitelist:
        return True
    rel = rel_path.replace('\\', '/')
    if rel.startswith('./'):
        rel = rel[2:]
    for pattern in whitelist:
        pat = pattern.replace('\\', '/')
        if pat.startswith('**/'):
            suffix = pat[3:]
            if fnmatch.fnmatchcase(rel, pat):
                return True
            if fnmatch.fnmatchcase(os.path.basename(rel), suffix):
                return True
            parts = rel.split('/')
            for i in range(len(parts)):
                candidate = '/'.join(parts[i:])
                if fnmatch.fnmatchcase(candidate, suffix):
                    return True
            continue
        if '/' not in pat:
            if '/' not in rel and fnmatch.fnmatchcase(rel, pat):
                return True
            continue
        if fnmatch.fnmatchcase(rel, pat):
            return True
    return False


class _IndexHrefParser(HTMLParser):
    """Collect href values from an autoindex HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: t.List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore
        if tag.lower() != 'a':
            return
        for key, value in attrs:
            if key.lower() == 'href' and value:
                self.hrefs.append(value)


class _FolderCtx:
    def __init__(
        self,
        *,
        timeout: t.Optional[float],
        progress: bool,
        whitelist: t.Optional[t.Iterable[str]],
        root_url: str,
        visited: t.Set[str],
    ) -> None:
        self.timeout = timeout
        self.progress = progress
        self.whitelist = whitelist
        self.root_url = root_url
        self.visited = visited


# (remote_url, local_path, relative_path)
_FileEntry = t.Tuple[str, str, str]


def _normalize_dir_url(url: str) -> str:
    if not url.endswith('/'):
        return url + '/'
    return url


def _is_under_base(child_url: str, base_url: str) -> bool:
    child = urlparse(child_url)
    base = urlparse(base_url)
    if (child.scheme, child.netloc) != (base.scheme, base.netloc):
        return False
    base_path = base.path if base.path.endswith('/') else base.path + '/'
    return child.path.startswith(base_path)


def _rel_path_from_urls(file_url: str, root_url: str) -> str:
    file_path = urlparse(file_url).path
    root_path = urlparse(root_url).path
    if not root_path.endswith('/'):
        root_path = root_path + '/'
    if file_path.startswith(root_path):
        return file_path[len(root_path) :]
    return os.path.basename(file_path)


def _write_response_body(response: HTTPResponse, local_filename: str, progress: bool) -> None:
    total_length = int(response.getheader('Content-Length') or '0')
    downloaded = 0
    block_size = 8192
    parent = os.path.dirname(local_filename)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(local_filename, 'wb') as out_file:
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
        logging.error('Download failed! maybe url timeout: %s', local_filename)
        raise OSError(f'Download failed: total_length {total_length} != downloaded {downloaded}: {local_filename}')


def _download_one_file(
    url: str,
    local_filename: str,
    timeout: t.Optional[float],
    progress: bool,
) -> None:
    """Shared low-level: fetch one URL body into a local file path."""
    if os.path.isdir(local_filename):
        raise OSError(f'local path is a directory, refuse to overwrite as file: {local_filename}')
    if os.path.exists(local_filename):
        os.remove(local_filename)
    logging.info('Downloading %s -> %s', url, local_filename)
    with urlopen(url, timeout=timeout) as response:
        _write_response_body(response, local_filename, progress)
    logging.info('Download complete!')


def _parse_index_entries(html_text: str, base_url: str) -> t.List[str]:
    parser = _IndexHrefParser()
    parser.feed(html_text)
    entries: t.List[str] = []
    seen: t.Set[str] = set()
    base_url = _normalize_dir_url(base_url)
    for href in parser.hrefs:
        if not href or href.startswith('#') or href.startswith('?'):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        # Drop query/fragment so sort links and anchors are ignored.
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        if clean in seen:
            continue
        if not _is_under_base(clean, base_url):
            continue
        if _normalize_dir_url(clean) == base_url:
            continue
        seen.add(clean)
        entries.append(clean)
    return entries


def _decode_html(body: bytes) -> str:
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return body.decode('latin-1', errors='replace')


def _collect_folder_files(
    url: str,
    local_dir: str,
    ctx: _FolderCtx,
    preloaded_html: t.Optional[str] = None,
) -> t.List[_FileEntry]:
    """Walk autoindex pages and return whitelisted file entries (no downloads)."""
    dir_url = _normalize_dir_url(url)
    if dir_url in ctx.visited:
        return []
    ctx.visited.add(dir_url)

    if preloaded_html is not None:
        final_url = dir_url
        html_text = preloaded_html
    else:
        with urlopen(dir_url, timeout=ctx.timeout) as response:
            final_url = _normalize_dir_url(response.geturl())
            content_type = (response.getheader('Content-Type') or '').lower()
            body = response.read()
        if 'html' not in content_type and not final_url.endswith('/'):
            raise OSError(f'Expected HTML directory index from {dir_url}, got {content_type!r}')
        html_text = _decode_html(body)

    files: t.List[_FileEntry] = []
    for entry_url in _parse_index_entries(html_text, final_url):
        is_dir = entry_url.endswith('/')
        if is_dir:
            sub_name = os.path.basename(entry_url.rstrip('/'))
            sub_local = os.path.join(local_dir, sub_name)
            files.extend(_collect_folder_files(entry_url, sub_local, ctx))
            continue
        rel = _rel_path_from_urls(entry_url, ctx.root_url)
        if not path_matches_whitelist(rel, ctx.whitelist):
            logger.debug('skip %s (whitelist)', rel)
            continue
        local_file = os.path.join(local_dir, os.path.basename(entry_url))
        files.append((entry_url, local_file, rel))
    return files


def _download_folder_entries(
    url: str,
    local_dir: str,
    ctx: _FolderCtx,
    preloaded_html: t.Optional[str] = None,
) -> None:
    os.makedirs(local_dir, exist_ok=True)
    logging.info('Downloading folder %s -> %s', _normalize_dir_url(url), local_dir)

    files = _collect_folder_files(url, local_dir, ctx, preloaded_html=preloaded_html)
    total = len(files)
    for index, (entry_url, local_file, rel) in enumerate(files, start=1):
        parent = os.path.dirname(local_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Folder mode: suppress per-file byte bars; show file-count progress instead.
        _download_one_file(entry_url, local_file, timeout=ctx.timeout, progress=False)
        if ctx.progress:
            _folder_progress(index, total, rel)

    if ctx.progress:
        if total:
            sys.stdout.write(f'\nDownloaded {total} files\n')
        else:
            sys.stdout.write('Downloaded 0 files\n')
        sys.stdout.flush()


def _reraise_download_error(url: str, exc: BaseException) -> None:
    logging.error('Download %s failed: %s', url, str(exc))
    if isinstance(exc, URLError):
        raise OSError(str(exc)) from exc
    raise exc


def download_file(
    url: str,
    local_filename: str,
    timeout: t.Optional[float] = None,
    progress: bool = True,
) -> None:
    """Download a single file from a URL.

    Args:
        url: The URL of the file to download.
        local_filename: Local file path to write.
        timeout: Timeout in seconds for blocking network operations.
        progress: Whether to show a byte progress bar.
    """
    try:
        _download_one_file(url, local_filename, timeout=timeout, progress=progress)
    except (URLError, OSError) as e:
        _reraise_download_error(url, e)


def download_dir(
    url: str,
    local_dir: str,
    timeout: t.Optional[float] = None,
    progress: bool = True,
    whitelist: t.Optional[t.Iterable[str]] = None,
) -> None:
    """Download an HTTP autoindex directory recursively.

    Expects an Apache/nginx-style directory listing (final URL usually ends
    with ``/``, or ``Content-Type`` is HTML). Entries are written under
    *local_dir*. Progress is a compact ``N/total`` file counter.

    Args:
        url: Directory URL (trailing slash optional; redirects are followed).
        local_dir: Local destination directory.
        timeout: Timeout in seconds for blocking network operations.
        progress: Whether to show file-count progress.
        whitelist: Optional relative-path globs. ``None`` / empty means all
            files. Examples: ``*.bin``, ``bootloader/*``, ``**/*.bin``.
    """
    try:
        logging.info('Downloading dir %s -> %s', url, local_dir)
        with urlopen(url, timeout=timeout) as response:
            final_url = _normalize_dir_url(response.geturl())
            content_type = (response.getheader('Content-Type') or '').lower()
            body = response.read()
        if 'html' not in content_type and not final_url.endswith('/'):
            raise OSError(f'Expected HTML directory index from {url}, got {content_type!r}')
        if os.path.isfile(local_dir):
            os.remove(local_dir)
        ctx = _FolderCtx(
            timeout=timeout,
            progress=progress,
            whitelist=whitelist,
            root_url=final_url,
            visited=set(),
        )
        _download_folder_entries(final_url, local_dir, ctx, preloaded_html=_decode_html(body))
    except (URLError, OSError) as e:
        _reraise_download_error(url, e)
