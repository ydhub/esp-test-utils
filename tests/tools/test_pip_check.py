import sys
from pathlib import Path
from unittest import mock

import pytest

from esptest.tools import pip_check

if sys.version_info >= (3, 8):
    from importlib.metadata import PackageNotFoundError

    patch_target = 'importlib.metadata.version'
    new_callable = None
else:
    import pkg_resources
    from pkg_resources import DistributionNotFound as PackageNotFoundError

    patch_target = 'pkg_resources.Distribution.version'
    new_callable = mock.PropertyMock


def test_simple_check_requirements(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reqs_content = """
# Comment line
pytest>=7.0.0
packaging>=23.0
    """
    reqs_file = tmp_path / 'requirements.txt'
    reqs_file.write_text(reqs_content)

    if new_callable:
        # unitest.mock cannot patch Distribution.version to return different value according to the package name
        def mock_version(self):
            return {'pytest': '7.4.3', 'packaging': '23.2'}[self.project_name]

        monkeypatch.setattr(pkg_resources.Distribution, 'version', property(mock_version))  # type: ignore
        assert pip_check.simple_check_requirements(reqs_file) is True
    else:
        with mock.patch(patch_target, autospec=True) as mock_version:
            mock_version.side_effect = lambda pkg: {'pytest': '7.4.3', 'packaging': '23.2'}[pkg]
            assert pip_check.simple_check_requirements(reqs_file) is True

    # Test invalid version
    reqs_content = 'pytest>=8.0.0'
    reqs_file.write_text(reqs_content)

    with mock.patch(patch_target, new_callable=new_callable) as mock_version:
        mock_version.return_value = '7.4.3'
        assert pip_check.simple_check_requirements(str(reqs_file)) is False
        assert 'pytest>=8.0.0' in caplog.text

    # Test missing package
    reqs_content = 'non-existent-package>=1.0.0'
    reqs_file.write_text(reqs_content)

    with mock.patch(patch_target, new_callable=new_callable) as mock_version:
        mock_version.side_effect = PackageNotFoundError()
        assert pip_check.simple_check_requirements(str(reqs_file)) is False
        assert reqs_content in caplog.text

    # Test invalid requirement format
    reqs_content = 'invalid=requirement=format'
    reqs_file.write_text(reqs_content)
    assert pip_check.simple_check_requirements(str(reqs_file)) is False
    assert reqs_content in caplog.text

    # Test empty file
    reqs_file.write_text('')
    assert pip_check.simple_check_requirements(str(reqs_file)) is True

    # Test recursive requirements
    main_reqs = tmp_path / 'main-requirements.txt'
    sub_reqs = tmp_path / 'sub-requirements.txt'

    main_reqs.write_text(f'-r {sub_reqs}')
    sub_reqs.write_text('pytest>=7.0.0')

    with mock.patch(patch_target, new_callable=new_callable) as mock_version:
        mock_version.return_value = '7.4.3'
        assert pip_check.simple_check_requirements(main_reqs) is True

    main_reqs.write_text(f'-r {sub_reqs}')
    sub_reqs.write_text('pytest>=7.0.0')

    with mock.patch(patch_target, new_callable=new_callable) as mock_version:
        mock_version.return_value = '6.4.3'
        assert pip_check.simple_check_requirements(str(main_reqs)) is False
        assert 'pytest>=7.0.0' in caplog.text


def test_simple_check_requirements_invalid_version_format(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test handling of invalid version format"""
    reqs_file = tmp_path / 'requirements.txt'
    reqs_file.write_text('pytest>=7.0.0')

    with mock.patch(patch_target, new_callable=new_callable) as mock_version:
        mock_version.return_value = 'invalid.version'
        assert pip_check.simple_check_requirements(reqs_file) is False
        assert 'pytest' in caplog.text


def test_simple_check_requirements_file_not_found() -> None:
    """Test handling of non-existent requirements file"""
    with pytest.raises(FileNotFoundError):
        pip_check.simple_check_requirements('non-existent-file.txt')


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
