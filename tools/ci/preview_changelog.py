import difflib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Union

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
CHANGELOG_FILE = 'CHANGELOG.md'
GITLAB_API_TOKEN = os.getenv('GITLAB_API_TOKEN')
CI_SERVER_URL = os.getenv('CI_SERVER_URL')
CI_PROJECT_ID = os.getenv('CI_PROJECT_ID')
CI_MERGE_REQUEST_IID = os.getenv('CI_MERGE_REQUEST_IID')


def add_or_modify_mr_notes(content: str, header: str) -> None:
    """Add or update the preview changelog note in a merge request."""
    import gitlab  # type: ignore[reportMissingImports]

    gl = gitlab.Gitlab(url=CI_SERVER_URL, private_token=GITLAB_API_TOKEN)
    gl.auth()
    project = gl.projects.get(CI_PROJECT_ID, lazy=True)
    mr = project.mergerequests.get(CI_MERGE_REQUEST_IID, lazy=True)

    discussions = mr.discussions.list(all=True, iter=True, per_page=100)
    for discussion in discussions:
        for note in discussion.attributes['notes']:
            if header not in note['body']:
                continue
            note_obj = discussion.notes.get(note['id'])
            note_obj.body = content
            note_obj.save()
            return

    note = mr.notes.create({'body': content})
    note.save()


def get_new_changelog(old_file: pathlib.Path, new_file: pathlib.Path) -> str:
    """Return lines added to the generated changelog."""
    with open(old_file, encoding='utf-8') as f1, open(new_file, encoding='utf-8') as f2:
        lines1 = f1.readlines()
        lines2 = f2.readlines()

    diff = difflib.ndiff(lines1, lines2)
    return ''.join(line[2:] for line in diff if line.startswith('+ '))


def is_bump_commit(commit_message: str) -> bool:
    return 'ci(bump' in commit_message or 'bump/new_version' in commit_message


def ensure_text(output: Union[bytes, str]) -> str:
    if not output:
        return ''
    if isinstance(output, bytes):
        return output.decode('utf-8')
    return output


def get_command_output(result: subprocess.CompletedProcess) -> str:
    return ensure_text(result.stdout) + ensure_text(result.stderr)


def format_cz_result(returncode: int, stdout: Union[bytes, str], stderr: Union[bytes, str]) -> str:
    """Format cz subprocess streams for CI logs."""
    out = ensure_text(stdout).rstrip() or '(empty)'
    err = ensure_text(stderr).rstrip() or '(empty)'
    return f'cz returncode={returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}'


def is_no_commits_to_bump(returncode: int, output: str) -> bool:
    # Commitizen NoneIncrementExit is 21; 13 is NoCommandFoundError and must not be treated as success.
    # With `cz --no-raise 21`, returncode becomes 0 and detection relies on the marker string.
    return '[NO_COMMITS_TO_BUMP]' in output or returncode == 21


def get_current_version(project_root: pathlib.Path) -> str:
    try:
        return (
            subprocess.check_output(
                ['git', 'describe', '--abbrev=0', '--tags'],
                cwd=str(project_root),
                stderr=subprocess.PIPE,
            )
            .decode('utf-8')
            .strip()
        )
    except subprocess.CalledProcessError:
        return 'unknown'


def build_preview_notes(current_version: str, next_version: str, changelog: str) -> str:
    return (
        '# Preview changelog\n'
        f'- from {current_version} to {next_version}\n'
        '## Changelog\n'
        '<details><summary> Click to see more instructions ... </summary><p><br>\n\n'
        f'{changelog}\n'
        '</details>\n'
    )


def main() -> None:
    current_version = get_current_version(PROJECT_ROOT)
    current_commit_msg = subprocess.check_output(
        ['git', 'log', '-1', '--pretty=%B'],
        cwd=str(PROJECT_ROOT),
    ).decode('utf-8')
    if is_bump_commit(current_commit_msg):
        print('Skip preview changelog for new version commit, exiting.')
        sys.exit(0)

    tmp_dir = tempfile.mkdtemp()
    tmp_repo_dir = pathlib.Path(tmp_dir) / PROJECT_ROOT.name
    try:
        shutil.copytree(str(PROJECT_ROOT), str(tmp_repo_dir))
        subprocess.check_call(
            ['git', 'log', '-10', '--pretty=oneline'],
            cwd=str(tmp_repo_dir),
        )

        get_next_result = subprocess.run(
            ['cz', '--no-raise', '21', 'bump', '--get-next', '--yes'],
            cwd=str(tmp_repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )
        get_next_output = get_command_output(get_next_result)
        if is_no_commits_to_bump(get_next_result.returncode, get_next_output):
            print('No commits to bump version, exiting.')
            print(
                format_cz_result(
                    get_next_result.returncode,
                    get_next_result.stdout,
                    get_next_result.stderr,
                )
            )
            sys.exit(0)
        if get_next_result.returncode:
            print(
                format_cz_result(
                    get_next_result.returncode,
                    get_next_result.stdout,
                    get_next_result.stderr,
                )
            )
            raise subprocess.CalledProcessError(
                get_next_result.returncode,
                get_next_result.args,
                output=get_next_result.stdout,
                stderr=get_next_result.stderr,
            )
        next_version = 'v' + get_next_result.stdout.strip()

        bump_result = subprocess.run(
            ['cz', '--no-raise', '21', 'bump', '--devrelease', '1', '--yes'],
            cwd=str(tmp_repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )
        bump_output = get_command_output(bump_result)
        if is_no_commits_to_bump(bump_result.returncode, bump_output):
            print('No commits to bump version, exiting.')
            print(
                format_cz_result(
                    bump_result.returncode,
                    bump_result.stdout,
                    bump_result.stderr,
                )
            )
            sys.exit(0)
        if bump_result.returncode:
            print(
                format_cz_result(
                    bump_result.returncode,
                    bump_result.stdout,
                    bump_result.stderr,
                )
            )
            raise subprocess.CalledProcessError(
                bump_result.returncode,
                bump_result.args,
                output=bump_result.stdout,
                stderr=bump_result.stderr,
            )

        changelog = get_new_changelog(
            PROJECT_ROOT / CHANGELOG_FILE,
            tmp_repo_dir / CHANGELOG_FILE,
        )
    except subprocess.CalledProcessError as e:
        print(f'Error during version bump: {type(e)}: {str(e)}')
        raise
    finally:
        shutil.rmtree(tmp_dir)

    notes = build_preview_notes(current_version, next_version, changelog)
    print(notes)
    if GITLAB_API_TOKEN and CI_MERGE_REQUEST_IID:
        add_or_modify_mr_notes(notes, header='# Preview changelog')
    else:
        print('not running in GitLab CI, skipping MR notes update')


if __name__ == '__main__':
    main()
