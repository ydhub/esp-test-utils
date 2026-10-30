"""Clone or fetch a git repository into a local checkout.

Successful fetches can be skipped for the rest of the process (``fetch_once``)
or for a time window (``refetch_interval``). Each checkout path remembers only
its latest success, so fetching ref A, then B, then A again contacts the remote
every time. Connection failures are retried with ``max_retry`` and
``retry_delay``. A missing ref falls back only when ``fallback_refs`` is set.
The last success time is stored in ``.git/esptest_fetch_stamp.json`` so a later
process can honor the interval.

This module does not protect concurrent use. Do not call it from multiple
threads at once: the in-process cache and the git checkout are not locked.
"""

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, NoReturn, Optional, Sequence, Set, Tuple, Union

from esptest.common.decorators import retry
from esptest.common.shell import CmdResult, RunCmdError, run_command

# Sentinel for fallback_refs: the remote HEAD branch, not a branch named "default".
DEFAULT_BRANCH = 'default'

# FETCH_HEAD mtime cannot replace this stamp. FETCH_HEAD records the URL and ref
# of the last fetch, but not the depth. mtime alone cannot tell which url, ref,
# and depth that fetch was. Skipping on time alone would also skip a request
# that just fetched a different ref.
_STAMP_NAME = 'esptest_fetch_stamp.json'


def _git(cmd: List[str]) -> CmdResult:
    """Run git and capture its text. A non-zero exit stays on the result."""
    return run_command(cmd, check=False, capture_output=True, text=True, errors='ignore')


class _LastFetch(NamedTuple):
    """Latest successful fetch for one checkout path.

    ``ref`` is the ref the caller asked for. ``resolved_ref`` is the ref that
    was checked out, which differs when a fallback ref was used.
    """

    url: str
    ref: str
    resolved_ref: str
    depth: int
    fetched_at: float


# The workspace has one HEAD, so an older ref must not stay skippable after a
# later fetch replaces it.
_LAST_FETCH: Dict[str, _LastFetch] = {}

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
    _LAST_FETCH.clear()


def _error_text(exc: RunCmdError) -> str:
    output = exc.output or ''
    if isinstance(output, bytes):
        return output.decode('utf-8', errors='replace')
    return str(output)


def _is_transient_git_error(exc: RunCmdError) -> bool:
    text = _error_text(exc).lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _is_missing_ref(exc: RunCmdError) -> bool:
    text = _error_text(exc).lower()
    return "couldn't find remote ref" in text or 'could not find remote ref' in text or 'not our ref' in text


def _raise_git_failure(result: CmdResult) -> NoReturn:
    exc = RunCmdError(
        str(result.cmd),
        result.output,
        retcode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    if _is_transient_git_error(exc):
        detail = _error_text(exc).strip() or str(exc)
        raise TransientFetchError(detail) from exc
    raise exc


def _run_git(cmd: List[str]) -> None:
    result = _git(cmd)
    if not result.ok:
        _raise_git_failure(result)


def check_git_repo(repo_path: str) -> None:
    if not os.path.isdir(repo_path):
        return

    git_dir = os.path.join(repo_path, '.git')
    if not os.path.isdir(git_dir):
        # path is not a git repository, remove it
        shutil.rmtree(repo_path)
        return

    result = _git(['git', '-C', repo_path, 'rev-parse', '--git-dir'])
    if not result.ok:
        logging.error(f'Git repo {repo_path} corrupted, removing...')
        shutil.rmtree(repo_path)


def _normalize_depth(depth: Optional[int]) -> int:
    if depth is None or depth <= 0:
        return 0
    return depth


def _stamp_path(path: str) -> Path:
    return Path(path) / '.git' / _STAMP_NAME


def _write_stamp(path: str, record: _LastFetch) -> None:
    git_dir = Path(path) / '.git'
    # Use pathlib so unit tests that mock os.path.isdir do not force a write.
    if not git_dir.is_dir():
        return
    payload = {
        'url': record.url,
        'ref': record.ref,
        'resolved_ref': record.resolved_ref,
        'depth': record.depth,
        'fetched_at': record.fetched_at,
    }
    dest = _stamp_path(path)
    tmp = git_dir / f'{_STAMP_NAME}.tmp'
    tmp.write_text(json.dumps(payload), encoding='utf-8')
    os.replace(str(tmp), str(dest))


def _read_last_fetch(path: str, url: str, ref: str, depth: int) -> Optional[_LastFetch]:
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
    ref_text = ref or ''
    if data.get('url') != url or data.get('ref') != ref_text:
        return None
    try:
        stamped_depth = int(data.get('depth') or 0)
        fetched_at = float(data['fetched_at'])
    except (TypeError, ValueError, KeyError):
        return None
    if stamped_depth != depth:
        return None
    resolved_ref = data.get('resolved_ref', ref_text)
    if not isinstance(resolved_ref, str):
        return None
    return _LastFetch(url, ref_text, resolved_ref, depth, fetched_at)


def _workspace_has_resolved_ref(path: str, resolved_ref: str) -> bool:
    """Return whether ``path`` is still checked out at ``resolved_ref``."""
    abbrev = _git(['git', '-C', path, 'rev-parse', '--abbrev-ref', 'HEAD'])
    if not abbrev.ok:
        return False
    if abbrev.output.strip() == resolved_ref:
        return True
    head = _git(['git', '-C', path, 'rev-parse', 'HEAD'])
    if not head.ok:
        return False
    return head.output.strip() == resolved_ref


def _record_still_checked_out(path: str, record: _LastFetch) -> bool:
    if record.resolved_ref == record.ref:
        return True
    return _workspace_has_resolved_ref(path, record.resolved_ref)


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
    record = _LAST_FETCH.get(os.path.abspath(path))
    ref_text = ref or ''
    matches = record is not None and record.url == url and record.ref == ref_text and record.depth == depth
    # A different remembered fetch means the checkout moved on. Do not fall
    # back to an older stamp for the requested ref.
    if record is not None and not matches:
        return False
    if matches and record is not None and not _record_still_checked_out(path, record):
        return False
    if matches and fetch_once:
        logging.info(f'Skip fetch for {path}: already fetched once in this process')
        return True
    if refetch_interval is not None and refetch_interval > 0:
        fetched_at: Optional[float]
        if matches and record is not None:
            fetched_at = record.fetched_at
        else:
            stamped = _read_last_fetch(path, url, ref, depth)
            if stamped is None or not _record_still_checked_out(path, stamped):
                fetched_at = None
            else:
                fetched_at = stamped.fetched_at
        if fetched_at is not None and (time.time() - fetched_at) < refetch_interval:
            age = time.time() - fetched_at
            logging.info(f'Skip fetch for {path}: last success was {age:.0f}s ago, interval is {refetch_interval:.0f}s')
            return True
    return False


def _mark_fetched(path: str, url: str, ref: str, resolved_ref: str, depth: int) -> None:
    fetched_at = time.time()
    ref_text = ref or ''
    resolved_text = resolved_ref or ''
    record = _LastFetch(url, ref_text, resolved_text, depth, fetched_at)
    _LAST_FETCH[os.path.abspath(path)] = record
    _write_stamp(path, record)


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
    result = _git(['git', 'ls-remote', '--symref', url, 'HEAD'])
    if not result.ok:
        _raise_git_failure(result)
    for line in result.output.splitlines():
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


def _clone_first_available(url: str, path: str, refs: Sequence[str], depth: int) -> str:
    """Fetch the first ref that exists and return that ref.

    ``default`` is the remote HEAD branch. The returned name is the ref that was
    checked out, after resolving that sentinel.
    """
    last_missing: Optional[RunCmdError] = None
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
            clone_or_fetch(url, path, resolved, depth)
            return resolved
        except RunCmdError as exc:
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
    _run_git(['git', '-C', path, 'clean', '-ffdx'])
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
    fallback_refs: Sequence[str] = (),
) -> None:
    """Clone or fetch ``url`` into ``path`` and check out ``ref``.

    The remote is not contacted in three cases. ``path`` must still exist, and
    :func:`check_git_repo` must not have removed it.

    - ``ref`` is empty and ``path`` is already a valid git repository.
    - ``fetch_once`` is set and the latest successful fetch of this path in this
      process used the same url, requested ref, and depth. The first call still
      contacts the remote. A fallback checkout is remembered under the requested
      ref, so the same arguments skip while HEAD is still the resolved ref.
      Fetching another ref or depth replaces that record.
    - ``refetch_interval`` is positive and that latest success is still inside
      the interval. The stamp in ``.git/esptest_fetch_stamp.json`` also stores
      only the latest success, for a later process.

    Not thread-safe. Overlapping calls are not serialized.

    Args:
        url: Git remote URL.
        path: Local checkout path.
        ref: Branch, tag, or commit. Empty skips the fetch when ``path`` already exists.
        depth: Shallow depth. ``None`` or ``0`` keeps full history.
        fetch_once: Skip when the latest successful fetch of this path in this process used the
            same url, requested ref, and depth. The first call still contacts the remote,
            including when the checkout already exists. A fallback hit is stored under the
            requested ref and skips only while HEAD is still the resolved ref. Switching to
            another ref and back fetches again.
        refetch_interval: Skip when that latest success is within this many seconds. ``None`` or
            a non-positive value disables the limit. A different ref or depth replaces the
            remembered fetch. A new process uses ``.git/esptest_fetch_stamp.json``.
        max_retry: Total attempts when git fails with a connection error. Other failures,
            such as a missing ref, are not retried.
        retry_delay: Seconds to wait between those attempts. A sequence must have ``max_retry - 1``
            values, one per retry. See :func:`esptest.common.decorators.retry`.
        fallback_refs: Refs to try, in order, when ``ref`` is missing. Empty by default,
            so a missing ref is an error. :data:`DEFAULT_BRANCH` (``default``) means the
            remote HEAD branch, not a branch named ``default``. Connection errors are
            still retried and are not treated as a missing ref.
    """
    if max_retry < 1:
        raise ValueError(f'max_retry must be >= 1, got {max_retry}')
    normalized_fallback = _normalize_fallback_refs(fallback_refs)
    normalized_depth = _normalize_depth(depth)
    ref_text = ref or ''

    checked_out: Optional[str] = None

    def _attempt() -> None:
        nonlocal checked_out
        check_git_repo(path)
        if not ref_text:
            if clone_or_fetch(url, path, ref_text, normalized_depth):
                checked_out = ''
            return
        checked_out = _clone_first_available(url, path, (ref_text, *normalized_fallback), normalized_depth)

    # Validate retry_delay before check_git_repo(), which may delete path.
    run_attempts = retry(max_retry=max_retry, on_exception=(TransientFetchError,), delay=retry_delay)(_attempt)

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

    try:
        run_attempts()
    except TransientFetchError as exc:
        cause = exc.__cause__
        if isinstance(cause, RunCmdError):
            # Re-raise the original git error. Pylint cannot tell __cause__ is an exception instance.
            raise cause from exc  # pylint: disable=raising-non-exception
        raise
    if checked_out is not None:
        _mark_fetched(path, url, ref_text, checked_out, normalized_depth)
