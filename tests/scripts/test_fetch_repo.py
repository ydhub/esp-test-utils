import os
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
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
