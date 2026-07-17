import urllib.request

import esptest.common.compat_typing as t

from .encoding import to_str


def _is_http_url(path_or_url: str) -> bool:
    return path_or_url.startswith('http://') or path_or_url.startswith('https://')


def _read_raw(path_or_url: str, timeout: t.Optional[float] = None) -> bytes:
    if _is_http_url(path_or_url):
        with urllib.request.urlopen(path_or_url, timeout=timeout) as response:
            return t.cast(bytes, response.read())
    with open(path_or_url, 'rb') as f:
        return f.read()


def get_file_bytes(path_or_url: str, *, timeout: t.Optional[float] = None) -> bytes:
    """Read raw bytes from a local path or http(s) URL."""
    return _read_raw(path_or_url, timeout=timeout)


def get_file_text(
    path_or_url: str,
    *,
    encoding: str = 'utf-8',
    errors: str = 'replace',
    timeout: t.Optional[float] = None,
) -> str:
    """Read text from a local path or http(s) URL.

    Local paths use text mode (same newline translation as ``Path.read_text``).
    HTTP(S) URLs decode raw response bytes via ``to_str``.
    """
    if _is_http_url(path_or_url):
        return to_str(_read_raw(path_or_url, timeout=timeout), encoding=encoding, errors=errors)
    with open(path_or_url, encoding=encoding, errors=errors) as f:
        return f.read()
