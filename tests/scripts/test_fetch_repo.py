import os
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Tuple
from unittest import mock

import pytest

from esptest.scripts import fetch_repo

MODULE_PATH = Path(__file__).resolve().parents[2] / 'esptest' / 'scripts' / 'fetch_repo.py'
SPEC = spec_from_file_location('fetch_repo_script', MODULE_PATH)
assert SPEC and SPEC.loader
fetch_repo_script = module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_repo_script)
CI_REPOSITORY_URL = os.getenv('CI_REPOSITORY_URL', '')
CI_COMMIT_SHA = os.getenv('CI_COMMIT_SHA', '')
CI_DEFAULT_BRANCH = os.getenv('CI_DEFAULT_BRANCH', 'main')


def _git_output(repo: str, *args: str) -> str:
    return subprocess.check_output(['git', '-C', repo, *args]).decode('utf-8').strip()


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
            mock.call(
                ['git', '-C', '/tmp/repo', 'clean', '-ffdx'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
    )


def test_fetch_existing_repo_with_ref_and_depth() -> None:
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', '/tmp/repo', 'release/v5.2', depth=1)

    run_cmd_mock.assert_has_calls(
        [
            mock.call(['git', '-C', '/tmp/repo', 'config', 'remote.origin.url', 'https://example.com/repo.git']),
            mock.call(['git', '-C', '/tmp/repo', 'fetch', 'origin', 'release/v5.2', '--depth', '1']),
            mock.call(['git', '-C', '/tmp/repo', 'checkout', '-f', '-B', 'release/v5.2', 'FETCH_HEAD']),
            mock.call(['git', '-C', '/tmp/repo', 'reset', '--hard']),
            mock.call(
                ['git', '-C', '/tmp/repo', 'clean', '-ffdx'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
    )


def test_fetch_existing_repo_with_short_ref() -> None:
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'check_git_repo'), mock.patch.object(
        fetch_repo_script.os.path, 'isdir', return_value=True
    ), mock.patch.object(fetch_repo_script, 'run_cmd') as run_cmd_mock:
    # fmt: on
        fetch_repo_script.fetch_repo('https://example.com/repo.git', '/tmp/repo', 'a1b2c3d4')

    run_cmd_mock.assert_has_calls(
        [
            mock.call(['git', '-C', '/tmp/repo', 'config', 'remote.origin.url', 'https://example.com/repo.git']),
            mock.call(['git', '-C', '/tmp/repo', 'fetch', 'origin', 'a1b2c3d4']),
            mock.call(['git', '-C', '/tmp/repo', 'checkout', '-f', '-B', 'a1b2c3d4', 'FETCH_HEAD']),
            mock.call(['git', '-C', '/tmp/repo', 'reset', '--hard']),
            mock.call(
                ['git', '-C', '/tmp/repo', 'clean', '-ffdx'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
    )


def test_parse_args_supports_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        'argv',
        ['prog', '--url', 'https://example.com/repo.git', '--path', '/tmp/repo', '--ref', 'abc123', '--depth', '5'],
    )
    args = fetch_repo_script.parse_args()
    assert args.depth == 5


def test_main_invokes_fetch_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    args = fetch_repo_script.argparse.Namespace(
        url='https://example.com/repo.git',
        path='/tmp/repo',
        ref='main',
        depth=2,
    )
    # fmt: off
    with mock.patch.object(fetch_repo_script, 'parse_args', return_value=args), mock.patch.object(
        fetch_repo_script, 'fetch_repo'
    ) as fetch_repo_mock, mock.patch.object(fetch_repo_script.logging, 'basicConfig'):
    # fmt: on
        fetch_repo_script.main()

    fetch_repo_mock.assert_called_once_with('https://example.com/repo.git', '/tmp/repo', 'main', depth=2)


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

    fetch_repo.main(['--url', remote_url, '--path', str(repo_path), '--ref', 'main', '--depth', '1'])

    assert _git_output(str(repo_path), 'rev-parse', 'HEAD') == main_sha
    assert not (repo_path / 'stale.txt').exists()


def test_fetch_repo_cleans_corrupted_repo_then_fetches(tmp_path: Path) -> None:
    remote_url, main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = tmp_path / 'repo'
    repo_path.mkdir()
    (repo_path / '.git').mkdir()

    fetch_repo.main(['--url', remote_url, '--path', str(repo_path), '--ref', 'main', '--depth', '1'])

    assert _git_output(str(repo_path), 'rev-parse', 'HEAD') == main_sha


@pytest.mark.parametrize(
    'second_ref_kind',
    ['branch', 'commit'],
)
def test_fetch_depth1_main_then_another_ref(tmp_path: Path, second_ref_kind: str) -> None:
    remote_url, main_sha, feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = str(tmp_path / 'repo')
    second_ref = 'feature' if second_ref_kind == 'branch' else feature_sha

    fetch_repo.main(['--url', remote_url, '--path', repo_path, '--ref', 'main', '--depth', '1'])
    assert os.path.isdir(os.path.join(repo_path, '.git'))
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == main_sha

    fetch_repo.main(['--url', remote_url, '--path', repo_path, '--ref', second_ref, '--depth', '1'])
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == feature_sha


def test_fetch_depth1_main_then_invalid_branch(tmp_path: Path) -> None:
    remote_url, main_sha, _feature_sha = _init_remote_with_main_and_feature(tmp_path)
    repo_path = str(tmp_path / 'repo')

    fetch_repo.main(['--url', remote_url, '--path', repo_path, '--ref', 'main', '--depth', '1'])
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == main_sha

    with pytest.raises(subprocess.CalledProcessError):
        fetch_repo.main(['--url', remote_url, '--path', repo_path, '--ref', 'no-such-branch', '--depth', '1'])

    # failed fetch must leave the existing checkout intact
    assert os.path.isdir(os.path.join(repo_path, '.git'))
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == main_sha


@pytest.mark.skipif(not CI_REPOSITORY_URL, reason='CI_REPOSITORY_URL is not set in CI')
def test_fetch_repo_via_commit_hash() -> None:
    # pass args to main
    cmd_args = ['--url', CI_REPOSITORY_URL, '--path', '/tmp/repo', '--ref', CI_COMMIT_SHA, '--depth', '1']
    fetch_repo.main(cmd_args)
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
    fetch_repo.main(['--url', CI_REPOSITORY_URL, '--path', repo_path, '--ref', CI_DEFAULT_BRANCH, '--depth', '1'])
    assert os.path.isdir(os.path.join(repo_path, '.git'))

    fetch_repo.main(['--url', CI_REPOSITORY_URL, '--path', repo_path, '--ref', CI_COMMIT_SHA, '--depth', '1'])
    assert _git_output(repo_path, 'rev-parse', 'HEAD') == CI_COMMIT_SHA
