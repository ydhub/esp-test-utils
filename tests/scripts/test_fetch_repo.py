import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator, List, Tuple
from unittest import mock

import pytest

import esptest.common.decorators as decorators
from esptest.common.shell import RunCmdError
from esptest.scripts import fetch_repo as fetch_repo_cli
from esptest.tools import fetch_repo as fetch_repo_script

CI_REPOSITORY_URL = os.getenv('CI_REPOSITORY_URL', '')
CI_COMMIT_SHA = os.getenv('CI_COMMIT_SHA', '')
CI_DEFAULT_BRANCH = os.getenv('CI_DEFAULT_BRANCH', 'main')
_URL = 'https://example.com/repo.git'
_CONNECT_STDERR = "fatal: unable to access 'https://example.com/repo.git': Could not resolve host: example.com"
_HTTP_503_STDERR = 'fatal: unable to access: The requested URL returned error: 503'
_MISSING_REF_STDERR = "fatal: couldn't find remote ref refs/heads/no-such-branch\n"


class _RetryClock:
    """Stand in for ``decorators.time`` without replacing the global ``time.sleep``."""

    def __init__(self, sleep: Callable[[float], None]) -> None:
        self.sleep = sleep

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


@pytest.fixture(autouse=True)
def _reset_fetch_cache() -> Iterator[None]:
    fetch_repo_script.clear_fetch_cache()
    yield
    fetch_repo_script.clear_fetch_cache()


def _git_output(repo: str, *args: str) -> str:
    return subprocess.check_output(['git', '-C', repo, *args]).decode('utf-8').strip()


def _rmtree(path: Path) -> None:
    """Remove ``path``, including read-only files created by git on Windows."""

    def _clear_readonly(func: Callable[..., Any], target: str, _exc: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:
        shutil.rmtree(str(path), onerror=_clear_readonly)


def _init_remote_with_main_and_feature(tmp_path: Path) -> Tuple[str, str, str]:
    """Create a bare remote with main and a diverging feature branch.

    Returns (remote_url, main_sha, feature_sha).
    """
    work = tmp_path / 'work'
    remote = tmp_path / 'remote.git'
    work.mkdir()
    subprocess.check_call(['git', 'init', '-b', 'main', str(work)])
    subprocess.check_call(['git', '-C', str(work), 'config', 'user.email', 'test@example.com'])
    subprocess.check_call(['git', '-C', str(work), 'config', 'user.name', 'test'])
    (work / 'file.txt').write_text('main\n')
    subprocess.check_call(['git', '-C', str(work), 'add', 'file.txt'])
    subprocess.check_call(['git', '-C', str(work), 'commit', '-m', 'main commit'])
    main_sha = _git_output(str(work), 'rev-parse', 'HEAD')

    subprocess.check_call(['git', '-C', str(work), 'checkout', '-b', 'feature'])
    (work / 'file.txt').write_text('feature\n')
    subprocess.check_call(['git', '-C', str(work), 'add', 'file.txt'])
    subprocess.check_call(['git', '-C', str(work), 'commit', '-m', 'feature commit'])
    feature_sha = _git_output(str(work), 'rev-parse', 'HEAD')

    subprocess.check_call(['git', 'clone', '--bare', str(work), str(remote)])
    return str(remote), main_sha, feature_sha


def test_clone_uses_depth_when_no_ref_and_path_missing() -> None:
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=False
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', '/tmp/repo', '', depth=3)

    run_cmd_mock.assert_called_once_with(['git', 'clone', 'https://example.com/repo.git', '/tmp/repo', '--depth', '3'])


def test_clone_without_depth_when_no_ref() -> None:
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=False
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', '/tmp/repo', '')

    run_cmd_mock.assert_called_once_with(['git', 'clone', 'https://example.com/repo.git', '/tmp/repo'])


def test_ref_inits_repo_and_fetches_when_path_missing() -> None:
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=False
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock, mock.patch.object(
        fetch_repo_script.os, 'makedirs'
    ) as makedirs_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', '/tmp/repo', 'v1.0.0')

    makedirs_mock.assert_called_once_with('/tmp/repo', exist_ok=True)
    run_cmd_mock.assert_has_calls(
        [
            mock.call(['git', '-C', '/tmp/repo', 'init']),
            mock.call(['git', '-C', '/tmp/repo', 'config', 'remote.origin.url', 'https://example.com/repo.git']),
            mock.call(['git', '-C', '/tmp/repo', 'fetch', 'origin', 'v1.0.0']),
            mock.call(['git', '-C', '/tmp/repo', 'checkout', '-f', '-B', 'v1.0.0', 'FETCH_HEAD']),
            mock.call(['git', '-C', '/tmp/repo', 'reset', '--hard']),
            mock.call(['git', '-C', '/tmp/repo', 'clean', '-ffdx']),
        ]
    )


def _checkout_with_git_dir(tmp_path: Path, name: str = 'repo') -> str:
    """Real ``.git`` so stamp writes succeed when ``os.path.isdir`` is mocked.

    Python 3.14 ``Path.is_dir`` calls ``os.path.isdir``. A mock that always
    returns true would otherwise make ``_write_stamp`` write into a missing directory.
    """
    repo = tmp_path / name
    (repo / '.git').mkdir(parents=True)
    return str(repo)


def test_fetch_existing_repo_with_ref_and_depth(tmp_path: Path) -> None:
    repo = _checkout_with_git_dir(tmp_path)
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', repo, 'release/v5.2', depth=1)

    run_cmd_mock.assert_has_calls(
        [
            mock.call(['git', '-C', repo, 'config', 'remote.origin.url', 'https://example.com/repo.git']),
            mock.call(['git', '-C', repo, 'fetch', 'origin', 'release/v5.2', '--depth', '1']),
            mock.call(['git', '-C', repo, 'checkout', '-f', '-B', 'release/v5.2', 'FETCH_HEAD']),
            mock.call(['git', '-C', repo, 'reset', '--hard']),
            mock.call(['git', '-C', repo, 'clean', '-ffdx']),
        ]
    )


def test_fetch_existing_repo_with_short_ref(tmp_path: Path) -> None:
    repo = _checkout_with_git_dir(tmp_path)
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', repo, 'a1b2c3d4')

    run_cmd_mock.assert_has_calls(
        [
            mock.call(['git', '-C', repo, 'config', 'remote.origin.url', 'https://example.com/repo.git']),
            mock.call(['git', '-C', repo, 'fetch', 'origin', 'a1b2c3d4']),
            mock.call(['git', '-C', repo, 'checkout', '-f', '-B', 'a1b2c3d4', 'FETCH_HEAD']),
            mock.call(['git', '-C', repo, 'reset', '--hard']),
            mock.call(['git', '-C', repo, 'clean', '-ffdx']),
        ]
    )


def test_parse_args_supports_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        'argv',
        ['prog', '--url', 'https://example.com/repo.git', '--path', '/tmp/repo', '--ref', 'abc123', '--depth', '5'],
    )
    args = fetch_repo_cli.parse_args()
    assert args.depth == 5


def test_main_invokes_fetch_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    args = fetch_repo_cli.argparse.Namespace(
        url='https://example.com/repo.git',
        path='/tmp/repo',
        ref='main',
        depth=2,
    )
    # fmt: off
    with mock.patch.object(fetch_repo_cli, 'parse_args', return_value=args), mock.patch.object(
        fetch_repo_cli, 'fetch_repo'
    ) as fetch_repo_mock, mock.patch.object(fetch_repo_cli.logging, 'basicConfig'):
    # fmt: on
        fetch_repo_cli.main()

    fetch_repo_mock.assert_called_once_with(
        'https://example.com/repo.git',
        '/tmp/repo',
        'main',
        depth=2,
    )


def test_no_git_commands_when_no_ref_and_path_exists() -> None:
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', '/tmp/repo', '')

    run_cmd_mock.assert_not_called()


def test_check_git_repo_noop_when_path_missing(tmp_path: Path) -> None:
    missing = tmp_path / 'missing'
    fetch_repo_script.check_git_repo(str(missing))
    assert not missing.exists()


def test_check_git_repo_removes_path_without_git_dir(tmp_path: Path) -> None:
    repo_path = tmp_path / 'not_a_repo'
    repo_path.mkdir()
    (repo_path / 'junk.txt').write_text('x\n')

    fetch_repo_script.check_git_repo(str(repo_path))

    assert not repo_path.exists()


def test_check_git_repo_removes_corrupted_git_repo(tmp_path: Path) -> None:
    repo_path = tmp_path / 'corrupt'
    repo_path.mkdir()
    (repo_path / '.git').mkdir()  # empty .git makes rev-parse fail

    fetch_repo_script.check_git_repo(str(repo_path))

    assert not repo_path.exists()


def test_check_git_repo_keeps_valid_repo(tmp_path: Path) -> None:
    repo_path = tmp_path / 'valid'
    subprocess.check_call(['git', 'init', '-b', 'main', str(repo_path)])

    fetch_repo_script.check_git_repo(str(repo_path))

    assert repo_path.is_dir()
    assert (repo_path / '.git').is_dir()


def test_fetch_repo_cleans_non_git_path_then_fetches(tmp_path: Path) -> None:
    remote_url, main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = tmp_path / 'repo'
    repo_path.mkdir()
    (repo_path / 'stale.txt').write_text('stale\n')

    fetch_repo_cli.main(['--url', remote_url, '--path', str(repo_path), '--ref', 'main', '--depth', '1'])

    assert _git_output(str(repo_path), 'rev-parse', 'HEAD') == main_sha
    assert not (repo_path / 'stale.txt').exists()


def test_fetch_repo_cleans_corrupted_repo_then_fetches(tmp_path: Path) -> None:
    remote_url, main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = tmp_path / 'repo'
    repo_path.mkdir()
    (repo_path / '.git').mkdir()

    fetch_repo_cli.main(['--url', remote_url, '--path', str(repo_path), '--ref', 'main', '--depth', '1'])

    assert _git_output(str(repo_path), 'rev-parse', 'HEAD') == main_sha


@pytest.mark.parametrize(
    'second_ref_kind',
    ['branch', 'commit'],
)
def test_fetch_depth1_main_then_another_ref(tmp_path: Path, second_ref_kind: str) -> None:
    remote_url, main_sha, feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = str(tmp_path / 'repo')
    second_ref = 'feature' if second_ref_kind == 'branch' else feature_sha

    fetch_repo_cli.main(['--url', remote_url, '--path', repo_path, '--ref', 'main', '--depth', '1'])
    assert os.path.isdir(os.path.join(repo_path, '.git'))
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == main_sha

    fetch_repo_cli.main(['--url', remote_url, '--path', repo_path, '--ref', second_ref, '--depth', '1'])
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == feature_sha


def _init_remote_with_branch(tmp_path: Path, branch: str) -> Tuple[str, str]:
    work = tmp_path / 'work'
    remote = tmp_path / 'remote.git'
    work.mkdir()
    subprocess.check_call(['git', 'init', '-b', branch, str(work)])
    subprocess.check_call(['git', '-C', str(work), 'config', 'user.email', 'test@example.com'])
    subprocess.check_call(['git', '-C', str(work), 'config', 'user.name', 'test'])
    (work / 'file.txt').write_text(branch + '\n')
    subprocess.check_call(['git', '-C', str(work), 'add', 'file.txt'])
    subprocess.check_call(['git', '-C', str(work), 'commit', '-m', branch])
    sha = _git_output(str(work), 'rev-parse', 'HEAD')
    subprocess.check_call(['git', 'clone', '--bare', str(work), str(remote)])
    return str(remote), sha


def test_missing_ref_without_fallback_keeps_checkout(tmp_path: Path) -> None:
    remote_url, main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = str(tmp_path / 'repo')

    fetch_repo_script.fetch_repo(remote_url, repo_path, 'main', depth=1)
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == main_sha

    with pytest.raises(RunCmdError):
        fetch_repo_script.fetch_repo(remote_url, repo_path, 'no-such-branch', depth=1, fallback_refs=())

    assert os.path.isdir(os.path.join(repo_path, '.git'))
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == main_sha


def test_missing_ref_does_not_fall_back_by_default(tmp_path: Path) -> None:
    remote_url, _develop_sha = _init_remote_with_branch(tmp_path, 'develop')
    repo_path = str(tmp_path / 'repo')

    with pytest.raises(RunCmdError):
        fetch_repo_cli.main(['--url', remote_url, '--path', repo_path, '--ref', 'no-such-branch', '--depth', '1'])

    assert not (tmp_path / 'repo' / 'file.txt').exists()


def test_explicit_default_fallback_checks_out_remote_head(tmp_path: Path) -> None:
    remote_url, develop_sha = _init_remote_with_branch(tmp_path, 'develop')
    repo_path = str(tmp_path / 'repo')

    fetch_repo_script.fetch_repo(
        remote_url,
        repo_path,
        'no-such-branch',
        depth=1,
        fallback_refs=(fetch_repo_script.DEFAULT_BRANCH,),
    )

    assert _git_output(repo_path, 'rev-parse', '--abbrev-ref', 'HEAD') == 'develop'
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == develop_sha


def test_invalid_retry_delay_keeps_existing_directory(tmp_path: Path) -> None:
    repo = tmp_path / 'not-a-repo'
    repo.mkdir()
    marker = repo / 'keep.txt'
    marker.write_text('keep')

    with pytest.raises(ValueError, match='max_retry - 1'):
        fetch_repo_script.fetch_repo(_URL, str(repo), 'main', max_retry=3, retry_delay=[0.2])

    assert marker.is_file()


def test_fallback_fetch_once_skips_same_request(tmp_path: Path) -> None:
    remote_url, _main_sha, feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = tmp_path / 'repo'
    repo = str(repo_path)

    fetch_repo_script.fetch_repo(
        remote_url,
        repo,
        'no-such-branch',
        depth=1,
        fallback_refs=('feature',),
        fetch_once=True,
    )
    stamp = json.loads((repo_path / '.git' / 'esptest_fetch_stamp.json').read_text(encoding='utf-8'))
    assert stamp['ref'] == 'no-such-branch'
    assert stamp['resolved_ref'] == 'feature'
    assert _git_output(repo, 'rev-parse', 'HEAD') == feature_sha

    _rmtree(tmp_path / 'remote.git')
    fetch_repo_script.fetch_repo(
        remote_url,
        repo,
        'no-such-branch',
        depth=1,
        fallback_refs=('feature',),
        fetch_once=True,
    )
    assert _git_output(repo, 'rev-parse', 'HEAD') == feature_sha

    fetch_repo_script.clear_fetch_cache()
    fetch_repo_script.fetch_repo(
        remote_url,
        repo,
        'no-such-branch',
        depth=1,
        fallback_refs=('feature',),
        refetch_interval=3600,
    )
    assert _git_output(repo, 'rev-parse', 'HEAD') == feature_sha


def test_fallback_fetch_once_refetches_when_head_moves(tmp_path: Path) -> None:
    remote_url, _main_sha, feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = tmp_path / 'repo'
    repo = str(repo_path)
    fetch_repo_script.fetch_repo(
        remote_url,
        repo,
        'no-such-branch',
        depth=1,
        fallback_refs=('feature',),
        fetch_once=True,
    )

    subprocess.check_call(['git', '-C', repo, 'config', 'user.email', 'test@example.com'])
    subprocess.check_call(['git', '-C', repo, 'config', 'user.name', 'test'])
    subprocess.check_call(['git', '-C', repo, 'checkout', '-B', 'other'])
    (repo_path / 'file.txt').write_text('other\n')
    subprocess.check_call(['git', '-C', repo, 'add', 'file.txt'])
    subprocess.check_call(['git', '-C', repo, 'commit', '-m', 'other'])
    assert _git_output(repo, 'rev-parse', 'HEAD') != feature_sha

    fetch_repo_script.fetch_repo(
        remote_url,
        repo,
        'no-such-branch',
        depth=1,
        fallback_refs=('feature',),
        fetch_once=True,
    )
    assert _git_output(repo, 'rev-parse', 'HEAD') == feature_sha


def test_fallback_refs_uses_first_existing_ref(tmp_path: Path) -> None:
    remote_url, _main_sha, feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = str(tmp_path / 'repo')

    fetch_repo_script.fetch_repo(
        remote_url,
        repo_path,
        'no-such-branch',
        depth=1,
        fallback_refs=('also-missing', 'feature'),
    )

    assert _git_output(repo_path, 'rev-parse', '--abbrev-ref', 'HEAD') == 'feature'
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == feature_sha


@pytest.mark.skipif(not CI_REPOSITORY_URL, reason='CI_REPOSITORY_URL is not set in CI')
def test_fetch_repo_via_commit_hash() -> None:
    # pass args to main
    cmd_args = ['--url', CI_REPOSITORY_URL, '--path', '/tmp/repo', '--ref', CI_COMMIT_SHA, '--depth', '1']
    fetch_repo_cli.main(cmd_args)
    # check if /tmp/repo exists and is a git repository
    assert os.path.isdir('/tmp/repo')
    assert os.path.isdir(os.path.join('/tmp/repo', '.git'))
    # check /tmp/repo HEAD is the same as CI_COMMIT_SHA
    assert (
        subprocess.check_output(['git', '-C', '/tmp/repo', 'rev-parse', 'HEAD']).decode('utf-8').strip()
        == CI_COMMIT_SHA
    )


@pytest.mark.skipif(
    not CI_REPOSITORY_URL or not CI_COMMIT_SHA,
    reason='CI_REPOSITORY_URL/CI_COMMIT_SHA is not set in CI',
)
def test_fetch_repo_depth1_default_branch_then_commit(tmp_path: Path) -> None:
    repo_path = str(tmp_path / 'repo')
    fetch_repo_cli.main(['--url', CI_REPOSITORY_URL, '--path', repo_path, '--ref', CI_DEFAULT_BRANCH, '--depth', '1'])
    assert os.path.isdir(os.path.join(repo_path, '.git'))

    fetch_repo_cli.main(['--url', CI_REPOSITORY_URL, '--path', repo_path, '--ref', CI_COMMIT_SHA, '--depth', '1'])
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == CI_COMMIT_SHA


def test_scripts_fetch_repo_exports_cli_only() -> None:
    from esptest.scripts import fetch_repo as script_mod

    assert script_mod.fetch_repo is fetch_repo_script.fetch_repo
    assert script_mod.main is fetch_repo_cli.main
    for name in ('DEFAULT_BRANCH', 'check_git_repo', 'clear_fetch_cache', 'clone_or_fetch', 'run_cmd'):
        assert not hasattr(script_mod, name)


def test_clone_or_fetch_skips_existing_path_without_ref() -> None:
    # fmt: off
    with mock.patch.object(fetch_repo_script.os.path, 'isdir', return_value=True), mock.patch.object(
        fetch_repo_script, 'run_cmd'
    ) as run_cmd_mock:
    # fmt: on
        fetched = fetch_repo_script.clone_or_fetch(_URL, '/tmp/repo', '', 0)

    assert fetched is False
    run_cmd_mock.assert_not_called()


def test_fallback_refs_rejects_a_string() -> None:
    with pytest.raises(TypeError, match='fallback_refs'):
        fetch_repo_script.fetch_repo(_URL, '/tmp/repo', 'main', fallback_refs='main')


def test_fetch_repo_rejects_non_positive_max_retry() -> None:
    with pytest.raises(ValueError, match='max_retry'):
        fetch_repo_script.fetch_repo(_URL, '/tmp/repo', 'main', max_retry=0)


def test_default_fetches_again_in_same_process(tmp_path: Path) -> None:
    repo = _checkout_with_git_dir(tmp_path)
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, repo, 'main')
        first = run_cmd_mock.call_count
        fetch_repo_script.fetch_repo(_URL, repo, 'main')

    assert first > 0
    assert run_cmd_mock.call_count == first * 2


def test_fetch_once_skips_second_call(tmp_path: Path) -> None:
    repo = _checkout_with_git_dir(tmp_path)
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, repo, 'main', fetch_once=True)
        first = run_cmd_mock.call_count
        fetch_repo_script.fetch_repo(_URL, repo, 'main', fetch_once=True)

    assert first > 0
    assert run_cmd_mock.call_count == first


def test_fetch_once_refetches_different_ref_or_depth(tmp_path: Path) -> None:
    repo = _checkout_with_git_dir(tmp_path)
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, repo, 'main', depth=1, fetch_once=True)
        after_main = run_cmd_mock.call_count
        fetch_repo_script.fetch_repo(_URL, repo, 'feature', depth=1, fetch_once=True)
        after_feature = run_cmd_mock.call_count
        fetch_repo_script.fetch_repo(_URL, repo, 'feature', depth=2, fetch_once=True)

    assert after_feature > after_main
    assert run_cmd_mock.call_count > after_feature


def test_fetch_once_refetches_when_switching_back_to_previous_ref(tmp_path: Path) -> None:
    remote_url, main_sha, feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo = str(tmp_path / 'repo')

    fetch_repo_script.fetch_repo(remote_url, repo, 'main', depth=1, fetch_once=True)
    assert _git_output(repo, 'rev-parse', 'HEAD') == main_sha
    fetch_repo_script.fetch_repo(remote_url, repo, 'feature', depth=1, fetch_once=True)
    assert _git_output(repo, 'rev-parse', 'HEAD') == feature_sha
    fetch_repo_script.fetch_repo(remote_url, repo, 'main', depth=1, fetch_once=True)

    assert _git_output(repo, 'rev-parse', 'HEAD') == main_sha


def test_refetch_interval_refetches_when_switching_back_to_previous_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _checkout_with_git_dir(tmp_path, 'repo-interval-switch')
    clock = {'now': 1_000_000.0}
    monkeypatch.setattr(fetch_repo_script.time, 'time', lambda: clock['now'])
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, repo, 'main', refetch_interval=50)
        after_main = run_cmd_mock.call_count
        clock['now'] += 1
        fetch_repo_script.fetch_repo(_URL, repo, 'feature', refetch_interval=50)
        after_feature = run_cmd_mock.call_count
        clock['now'] += 1
        fetch_repo_script.fetch_repo(_URL, repo, 'main', refetch_interval=50)

    assert after_feature > after_main
    assert run_cmd_mock.call_count > after_feature


def test_refetch_interval_skips_until_window_expires(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = _checkout_with_git_dir(tmp_path, 'repo-interval')
    clock = {'now': 1_000_000.0}
    monkeypatch.setattr(fetch_repo_script.time, 'time', lambda: clock['now'])
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, repo, 'main', refetch_interval=50)
        first = run_cmd_mock.call_count
        clock['now'] += 10
        fetch_repo_script.fetch_repo(_URL, repo, 'main', refetch_interval=50)
        assert run_cmd_mock.call_count == first
        clock['now'] += 50
        fetch_repo_script.fetch_repo(_URL, repo, 'main', refetch_interval=50)

    assert first > 0
    assert run_cmd_mock.call_count > first


def test_refetch_interval_skips_when_stamp_is_fresh(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    (repo / '.git').mkdir(parents=True)
    payload = {'url': _URL, 'ref': 'main', 'depth': 1, 'fetched_at': time.time()}
    (repo / '.git' / 'esptest_fetch_stamp.json').write_text(json.dumps(payload), encoding='utf-8')

    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script, 'run_cmd'
    ) as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, str(repo), 'main', depth=1, refetch_interval=3600)

    run_cmd_mock.assert_not_called()


def test_refetch_interval_ignores_stale_or_other_ref_stamp(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    (repo / '.git').mkdir(parents=True)
    payload = {'url': _URL, 'ref': 'main', 'depth': 1, 'fetched_at': time.time() - 7200}
    (repo / '.git' / 'esptest_fetch_stamp.json').write_text(json.dumps(payload), encoding='utf-8')

    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script, 'run_cmd'
    ) as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, str(repo), 'main', depth=1, refetch_interval=3600)
        stale_calls = run_cmd_mock.call_count
        fetch_repo_script.clear_fetch_cache()
        fetch_repo_script.fetch_repo(_URL, str(repo), 'feature', depth=1, refetch_interval=3600)

    assert stale_calls > 0
    assert run_cmd_mock.call_count > stale_calls


@pytest.mark.parametrize('stderr', [_CONNECT_STDERR, _HTTP_503_STDERR])
def test_fetch_retries_transient_git_errors(stderr: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorded: List[float] = []

    def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(decorators, 'time', _RetryClock(_record))
    repo = _checkout_with_git_dir(tmp_path)
    state = {'n': 0}

    def _run(cmd: List[str], **_kwargs: Any) -> None:
        if 'fetch' in cmd:
            state['n'] += 1
            if state['n'] < 3:
                raise RunCmdError(str(cmd), stderr)

    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd', side_effect=_run):
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, repo, 'main', max_retry=3, retry_delay=[0.5, 2.0])

    assert state['n'] == 3
    assert recorded == [0.5, 2.0]


def test_fetch_raises_called_process_error_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decorators, 'time', _RetryClock(lambda _seconds: None))
    state = {'n': 0}

    def _run(cmd: List[str], **_kwargs: Any) -> None:
        if 'fetch' in cmd:
            state['n'] += 1
            raise RunCmdError(str(cmd), _CONNECT_STDERR)

    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd', side_effect=_run), pytest.raises(RunCmdError):
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, '/tmp/repo', 'main', max_retry=2, retry_delay=0)

    assert state['n'] == 2


def test_fetch_does_not_retry_missing_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: List[float] = []

    def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(decorators, 'time', _RetryClock(_record))
    state = {'n': 0}

    def _run(cmd: List[str], **_kwargs: Any) -> None:
        if 'fetch' in cmd:
            state['n'] += 1
            raise RunCmdError(str(cmd), _MISSING_REF_STDERR)

    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd', side_effect=_run), pytest.raises(RunCmdError):
    # fmt: on
        fetch_repo_script.fetch_repo(_URL, '/tmp/repo', 'main', max_retry=3, retry_delay=5, fallback_refs=())

    assert state['n'] == 1
    assert recorded == []


def test_fetch_once_skips_after_remote_removed(tmp_path: Path) -> None:
    remote_url, main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = str(tmp_path / 'repo')

    fetch_repo_script.fetch_repo(remote_url, repo_path, 'main', depth=1, fetch_once=True)
    _rmtree(tmp_path / 'remote.git')
    fetch_repo_script.fetch_repo(remote_url, repo_path, 'main', depth=1, fetch_once=True)

    assert _git_output(repo_path, 'rev-parse', 'HEAD') == main_sha


def test_fetch_once_does_not_reuse_stamp_after_cache_clear(tmp_path: Path) -> None:
    remote_url, _main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = str(tmp_path / 'repo')

    fetch_repo_script.fetch_repo(remote_url, repo_path, 'main', depth=1, fetch_once=True)
    fetch_repo_script.clear_fetch_cache()
    _rmtree(tmp_path / 'remote.git')
    with pytest.raises(RunCmdError):
        fetch_repo_script.fetch_repo(remote_url, repo_path, 'main', depth=1, fetch_once=True)


def test_refetch_interval_uses_stamp_after_cache_clear(tmp_path: Path) -> None:
    remote_url, main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = tmp_path / 'repo'
    repo = str(repo_path)

    fetch_repo_script.fetch_repo(remote_url, repo, 'main', depth=1, refetch_interval=3600)
    _rmtree(tmp_path / 'remote.git')
    fetch_repo_script.clear_fetch_cache()
    fetch_repo_script.fetch_repo(remote_url, repo, 'main', depth=1, refetch_interval=3600)
    assert _git_output(repo, 'rev-parse', 'HEAD') == main_sha

    stamp = repo_path / '.git' / 'esptest_fetch_stamp.json'
    payload = json.loads(stamp.read_text(encoding='utf-8'))
    payload['fetched_at'] = time.time() - 7200
    stamp.write_text(json.dumps(payload), encoding='utf-8')
    fetch_repo_script.clear_fetch_cache()
    with pytest.raises(RunCmdError):
        fetch_repo_script.fetch_repo(remote_url, repo, 'main', depth=1, refetch_interval=3600)
