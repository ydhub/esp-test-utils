import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREVIEW_CHANGELOG_PATH = PROJECT_ROOT / 'tools' / 'ci' / 'preview_changelog.py'


def _load_preview_changelog_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location('preview_changelog', PREVIEW_CHANGELOG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_new_changelog_returns_added_lines_only(tmp_path: Path) -> None:
    preview_changelog = _load_preview_changelog_module()
    old_changelog = tmp_path / 'old.md'
    new_changelog = tmp_path / 'new.md'

    old_changelog.write_text('## v0.1.0\n\n- feat: old feature\n', encoding='utf-8')
    new_changelog.write_text(
        '## v0.2.0\n\n- feat: new feature (1234567)\n\n## v0.1.0\n\n- feat: old feature\n',
        encoding='utf-8',
    )

    assert preview_changelog.get_new_changelog(old_changelog, new_changelog) == (
        '## v0.2.0\n\n- feat: new feature (1234567)\n\n'
    )


def test_is_bump_commit_detects_release_bump_messages() -> None:
    preview_changelog = _load_preview_changelog_module()

    assert preview_changelog.is_bump_commit('ci(bump-version): bump release version to v0.5.0') is True
    assert preview_changelog.is_bump_commit('Merge branch bump/new_version into main') is True
    assert preview_changelog.is_bump_commit('feat: add preview changelog') is False


def test_is_no_commits_to_bump_handles_commitizen_output_and_exit_codes() -> None:
    preview_changelog = _load_preview_changelog_module()

    assert preview_changelog.is_no_commits_to_bump(21, '[NO_COMMITS_TO_BUMP]\nNo eligible commits') is True
    assert preview_changelog.is_no_commits_to_bump(0, '[NO_COMMITS_TO_BUMP]\nNo eligible commits') is True
    # 13 is commitizen NoCommandFoundError, not "no commits to bump"
    assert preview_changelog.is_no_commits_to_bump(13, '') is False
    assert preview_changelog.is_no_commits_to_bump(1, 'unexpected error') is False


def test_format_cz_result_includes_returncode_stdout_and_stderr() -> None:
    preview_changelog = _load_preview_changelog_module()

    formatted = preview_changelog.format_cz_result(
        returncode=21,
        stdout='0.6.0\n',
        stderr='[NO_COMMITS_TO_BUMP]\nThe commits found are not eligible to be bumped\n',
    )

    assert 'returncode=21' in formatted
    assert '--- stdout ---' in formatted
    assert '0.6.0' in formatted
    assert '--- stderr ---' in formatted
    assert '[NO_COMMITS_TO_BUMP]' in formatted


def test_build_preview_notes_includes_version_range_and_changelog() -> None:
    preview_changelog = _load_preview_changelog_module()

    notes = preview_changelog.build_preview_notes(
        current_version='v0.5.0',
        next_version='v0.6.0',
        changelog='- feat: add preview changelog (abcdef0)\n',
    )

    assert notes.startswith('# Preview changelog\n')
    assert '- from v0.5.0 to v0.6.0\n' in notes
    assert '## Changelog\n' in notes
    assert '- feat: add preview changelog (abcdef0)\n' in notes


if __name__ == '__main__':
    pytest.main()
