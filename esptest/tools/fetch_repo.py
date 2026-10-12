"""Clone or fetch a git repository into a local checkout.

Successful fetches can be skipped for the rest of the process (``fetch_once``)
or for a time window (``refetch_interval``). Connection failures are retried
with ``max_retry`` and ``retry_delay``. A missing ref falls back to
``fallback_refs``, which defaults to the remote default branch. The last success
time is stored in ``.git/esptest_fetch_stamp.json`` so a later process can honor
the interval.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from esptest.common.decorators import retry

# Sentinel for fallback_refs: the remote HEAD branch, not a branch named "default".
DEFAULT_BRANCH = 'default'

# FETCH_HEAD mtime cannot replace this stamp. FETCH_HEAD records the URL and ref
# of the last fetch, but not the depth. mtime alone cannot tell which url, ref,
# and depth that fetch was. Skipping on time alone would also skip a request
# that just fetched a different ref.
_STAMP_NAME = 'esptest_fetch_stamp.json'
_CacheKey = Tuple[str, str, str, int]
_FETCHED_AT: Dict[_CacheKey, float] = {}
_FETCH_LOCK = threading.Lock()

# Git prints these on transient network failures. Missing refs and auth errors are not included.
_TRANSIENT_MARKERS: Tuple[str, ...] = (
    'could not resolve host',
    'name or service not known',
    'temporary failure in name resolution',
    'failed to connect',
    'connection timed out',
    'connection refused',
    'connection reset',
    'network is unreachable',
    'no route to host',
    'operation timed out',
    'early eof',
    'rpc failed',
    'empty reply from server',
    'recv failure',
    'ssl_error_syscall',
    'gnutls_handshake',
    'the tls connection was non-properly terminated',
    'could not connect',
    'the requested url returned error: 408',
    'the requested url returned error: 429',
    'the requested url returned error: 5',
)


class TransientFetchError(RuntimeError):
    """Git clone/fetch failed because of a transient network error."""


def clear_fetch_cache() -> None:
    """Drop in-process fetch memory. Stamp files on disk are kept."""
    with _FETCH_LOCK:
        _FETCHED_AT.clear()


def run_cmd(cmd: List[str], **kwargs: Any) -> None:
    logging.debug(f'Running command: {" ".join(cmd)}')
    if 'stderr' in kwargs:
        subprocess.run(cmd, check=True, **kwargs)
        return
    _run_cmd_tee_stderr(cmd, **kwargs)


def _mirror_stderr(line: bytes) -> None:
    try:
        sys.stderr.buffer.write(line)
        sys.stderr.buffer.flush()
    except OSError:
        logging.debug('Failed to mirror git stderr', exc_info=True)


def _run_cmd_tee_stderr(cmd: List[str], **kwargs: Any) -> None:
    """Run ``cmd``, copy stderr to the console, and keep it for error checks."""
    chunks: List[bytes] = []
    with subprocess.Popen(cmd, stderr=subprocess.PIPE, **kwargs) as process:
        stderr_pipe = process.stderr
        if stderr_pipe is None:
            raise RuntimeError('stderr pipe was not created')
        while True:
            line = stderr_pipe.readline()
            if not line:
                break
            chunks.append(line)
            _mirror_stderr(line)
        returncode = process.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd, stderr=b''.join(chunks))


def _error_text(exc: subprocess.CalledProcessError) -> str:
    chunks: List[str] = []
    for stream in (exc.stderr, exc.stdout):
        if not stream:
            continue
        if isinstance(stream, bytes):
            chunks.append(stream.decode('utf-8', errors='replace'))
        else:
            chunks.append(str(stream))
    return '\n'.join(chunks)


def _is_transient_git_error(exc: subprocess.CalledProcessError) -> bool:
    text = _error_text(exc).lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _is_missing_ref(exc: subprocess.CalledProcessError) -> bool:
    text = _error_text(exc).lower()
    return "couldn't find remote ref" in text or 'could not find remote ref' in text or 'not our ref' in text


def _run_git(cmd: List[str], **kwargs: Any) -> None:
    try:
        run_cmd(cmd, **kwargs)
    except subprocess.CalledProcessError as exc:
        if _is_transient_git_error(exc):
            detail = _error_text(exc).strip() or str(exc)
            raise TransientFetchError(detail) from exc
        raise


def check_git_repo(repo_path: str) -> None:
    if not os.path.isdir(repo_path):
        return

    git_dir = os.path.join(repo_path, '.git')
    if not os.path.isdir(git_dir):
        # path is not a git repository, remove it
        shutil.rmtree(repo_path)
        return

    try:
        run_cmd(['git', '-C', repo_path, 'rev-parse', '--git-dir'])
    except subprocess.CalledProcessError:
        logging.error(f'Git repo {repo_path} corrupted, removing...')
        shutil.rmtree(repo_path)


def _normalize_depth(depth: Optional[int]) -> int:
    if depth is None or depth <= 0:
        return 0
    return depth


def _cache_key(path: str, url: str, ref: str, depth: int) -> _CacheKey:
    return (os.path.abspath(path), url, ref or '', depth)


def _stamp_path(path: str) -> Path:
    return Path(path) / '.git' / _STAMP_NAME


def _write_stamp(path: str, url: str, ref: str, depth: int, fetched_at: float) -> None:
    git_dir = Path(path) / '.git'
    # Use pathlib so unit tests that mock os.path.isdir do not force a write.
    if not git_dir.is_dir():
        return
    payload = {
        'url': url,
        'ref': ref or '',
        'depth': depth,
        'fetched_at': fetched_at,
    }
    dest = _stamp_path(path)
    tmp = git_dir / f'{_STAMP_NAME}.tmp'
    tmp.write_text(json.dumps(payload), encoding='utf-8')
    os.replace(str(tmp), str(dest))


def _read_fetched_at(path: str, url: str, ref: str, depth: int) -> Optional[float]:
    dest = _stamp_path(path)
    if not dest.is_file():
        return None
    try:
        data = json.loads(dest.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeError):
        logging.warning(f'Ignore unreadable fetch stamp {dest}')
        return None
    if not isinstance(data, dict):
        return None
    if data.get('url') != url or data.get('ref') != (ref or ''):
        return None
    try:
        stamped_depth = int(data.get('depth') or 0)
        fetched_at = float(data['fetched_at'])
    except (TypeError, ValueError, KeyError):
        return None
    if stamped_depth != depth:
        return None
    return fetched_at


def _should_skip(
    path: str,
    url: str,
    ref: str,
    depth: int,
    *,
    fetch_once: bool,
    refetch_interval: Optional[float],
) -> bool:
    if not os.path.isdir(path):
        return False
    key = _cache_key(path, url, ref, depth)
    with _FETCH_LOCK:
        fetched_at = _FETCHED_AT.get(key)
        seen = key in _FETCHED_AT
    if fetch_once and seen:
        logging.info(f'Skip fetch for {path}: already fetched once in this process')
        return True
    if refetch_interval is not None and refetch_interval > 0:
        if fetched_at is None:
            fetched_at = _read_fetched_at(path, url, ref, depth)
        if fetched_at is not None and (time.time() - fetched_at) < refetch_interval:
            age = time.time() - fetched_at
            logging.info(f'Skip fetch for {path}: last success was {age:.0f}s ago, interval is {refetch_interval:.0f}s')
            return True
    return False


def _mark_fetched(path: str, url: str, ref: str, depth: int) -> None:
    fetched_at = time.time()
    key = _cache_key(path, url, ref, depth)
    with _FETCH_LOCK:
        _FETCHED_AT[key] = fetched_at
    _write_stamp(path, url, ref, depth, fetched_at)


def _normalize_fallback_refs(fallback_refs: Sequence[str]) -> Tuple[str, ...]:
    if isinstance(fallback_refs, (str, bytes)):
        raise TypeError('fallback_refs must be a sequence of ref names')
    refs: List[str] = []
    for item in fallback_refs:
        if not isinstance(item, str) or not item:
            raise ValueError(f'fallback ref must be a non-empty string, got {item!r}')
        refs.append(item)
    return tuple(refs)


def _remote_default_branch(url: str) -> str:
    """Return the remote HEAD branch name, such as ``main`` or ``master``."""
    cmd = ['git', 'ls-remote', '--symref', url, 'HEAD']
    try:
        completed = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        if _is_transient_git_error(exc):
            detail = _error_text(exc).strip() or str(exc)
            raise TransientFetchError(detail) from exc
        raise
    text = completed.stdout.decode('utf-8', errors='replace')
    for line in text.splitlines():
        if not line.startswith('ref:'):
            continue
        parts = line.split()
        if len(parts) < 2 or not parts[1].startswith('refs/heads/'):
            continue
        return parts[1][len('refs/heads/') :]
    raise RuntimeError(f'Cannot resolve default branch for {url}')


def _resolve_ref(url: str, ref: str, resolved_default: List[str]) -> str:
    if ref != DEFAULT_BRANCH:
        return ref
    if not resolved_default:
        resolved_default.append(_remote_default_branch(url))
    return resolved_default[0]


def _clone_first_available(url: str, path: str, refs: Sequence[str], depth: int) -> bool:
    """Fetch the first ref that exists. ``default`` is the remote HEAD branch."""
    last_missing: Optional[subprocess.CalledProcessError] = None
    seen: Set[str] = set()
    resolved_default: List[str] = []
    for ref in refs:
        resolved = _resolve_ref(url, ref, resolved_default)
        if resolved in seen:
            continue
        seen.add(resolved)
        if last_missing is not None:
            logging.warning(f'Ref not found in {url}, trying {resolved}')
        try:
            return clone_or_fetch(url, path, resolved, depth)
        except subprocess.CalledProcessError as exc:
            if not _is_missing_ref(exc):
                raise
            last_missing = exc
            logging.warning(f'Ref {resolved} not found in {url}')
    if last_missing is None:
        raise RuntimeError('no ref to fetch')
    raise last_missing


def clone_or_fetch(url: str, path: str, ref: str, depth: int) -> bool:
    """Clone or fetch ``ref`` into ``path``.

    Unlike :func:`fetch_repo`, this does not check the checkout, skip a recent
    fetch, or retry. A connection error still raises :class:`TransientFetchError`.

    Args:
        url: Git remote URL.
        path: Local checkout path.
        ref: Branch, tag, or commit. Empty clones the default branch, or skips
            the fetch when ``path`` already exists.
        depth: Shallow depth. ``0`` keeps full history.

    Returns:
        False when ``path`` already exists and ``ref`` is empty. True after a
        clone or fetch.
    """
    # ref not set, clone default branch
    if not ref:
        if os.path.isdir(path):
            # path is a git repository, but no ref provided
            logging.warning(f'Path {path} already exists, but no ref provided, skipping fetch...')
            return False
        # clone repo from remote url with default branch
        clone_args = ['git', 'clone', url, path]
        if depth:
            clone_args.extend(['--depth', str(depth)])
        _run_git(clone_args)
        return True

    # fetch specific ref
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        _run_git(['git', '-C', path, 'init'])

    # path is a git repository, configure remote origin url and fetch
    # ref may be a branch, tag or commit hash.
    # always checkout to new branch with FETCH_HEAD
    _run_git(['git', '-C', path, 'config', 'remote.origin.url', url])
    fetch_args = ['git', '-C', path, 'fetch', 'origin', ref]
    if depth:
        fetch_args.extend(['--depth', str(depth)])
    _run_git(fetch_args)
    _run_git(['git', '-C', path, 'checkout', '-f', '-B', ref, 'FETCH_HEAD'])
    _run_git(['git', '-C', path, 'reset', '--hard'])
    _run_git(['git', '-C', path, 'clean', '-ffdx'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def fetch_repo(  # pylint: disable=too-many-arguments
    url: str,
    path: str,
    ref: Optional[str],
    depth: Optional[int] = None,
    *,
    fetch_once: bool = False,
    refetch_interval: Optional[float] = None,
    max_retry: int = 1,
    retry_delay: Union[float, Sequence[float]] = 0,
    fallback_refs: Sequence[str] = (DEFAULT_BRANCH,),
) -> None:
    """Clone or fetch ``url`` into ``path`` and check out ``ref``.

    The remote is not contacted in three cases. ``path`` must still exist, and
    :func:`check_git_repo` must not have removed it.

    - ``ref`` is empty and ``path`` is already a valid git repository.
    - ``fetch_once`` is set and this process already fetched the same path, url,
      ref, and depth. The first call still contacts the remote.
    - ``refetch_interval`` is positive and that same fetch succeeded within the
      interval. The time is kept in memory and in ``.git/esptest_fetch_stamp.json``.

    Args:
        url: Git remote URL.
        path: Local checkout path.
        ref: Branch, tag, or commit. Empty skips the fetch when ``path`` already exists.
        depth: Shallow depth. ``None`` or ``0`` keeps full history.
        fetch_once: Fetch the same path, url, ref, and depth at most once in this process.
            The first call still contacts the remote, including when the checkout already exists.
        refetch_interval: Skip the fetch when the same checkout succeeded within this many
            seconds. ``None`` or a non-positive value disables the limit. The timestamp is kept
            in memory and in ``.git/esptest_fetch_stamp.json``.
        max_retry: Total attempts when git fails with a connection error. Other failures,
            such as a missing ref, are not retried.
        retry_delay: Seconds to wait between those attempts. A sequence must have ``max_retry - 1``
            values, one per retry. See :func:`esptest.common.decorators.retry`.
        fallback_refs: Refs to try, in order, when ``ref`` is missing. :data:`DEFAULT_BRANCH`
            (``default``) means the remote HEAD branch, not a branch named ``default``.
            The default is that one branch. Pass an empty sequence to disable fallback.
            Connection errors are still retried and are not treated as a missing ref.
    """
    if max_retry < 1:
        raise ValueError(f'max_retry must be >= 1, got {max_retry}')
    normalized_fallback = _normalize_fallback_refs(fallback_refs)
    normalized_depth = _normalize_depth(depth)
    ref_text = ref or ''

    check_git_repo(path)
    if _should_skip(
        path,
        url,
        ref_text,
        normalized_depth,
        fetch_once=fetch_once,
        refetch_interval=refetch_interval,
    ):
        return

    fetched = False

    def _attempt() -> None:
        nonlocal fetched
        check_git_repo(path)
        if not ref_text:
            fetched = clone_or_fetch(url, path, ref_text, normalized_depth)
            return
        fetched = _clone_first_available(url, path, (ref_text, *normalized_fallback), normalized_depth)

    try:
        retry(max_retry=max_retry, on_exception=(TransientFetchError,), delay=retry_delay)(_attempt)()
    except TransientFetchError as exc:
        cause = exc.__cause__
        if isinstance(cause, subprocess.CalledProcessError):
            # Re-raise the original git error. Pylint cannot tell __cause__ is an exception instance.
            raise cause from exc  # pylint: disable=raising-non-exception
        raise
    if fetched:
        _mark_fetched(path, url, ref_text, normalized_depth)
