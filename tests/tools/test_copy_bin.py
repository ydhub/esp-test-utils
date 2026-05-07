import zipfile
from pathlib import Path

import pytest

import esptest.tools.copy_bin as copy_bin_module
from esptest.tools.copy_bin import copy_bin_to_new_path


def _write_text(path: Path, content: str = 'x') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def test_copy_bin_to_new_path_zip_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copy_bin_module, 'IDF_PATH', '')

    from_dir = tmp_path / 'build'
    _write_text(from_dir / 'app.bin')
    _write_text(from_dir / 'bootloader' / 'bootloader.bin')
    _write_text(from_dir / 'partition_table' / 'partition-table.bin')
    _write_text(from_dir / 'flasher_args.json', '{}')

    to_path = tmp_path / 'artifacts' / 'app_bins.zip'
    copy_bin_to_new_path(str(from_dir), str(to_path), zip_output=True, force=False, copy_elf=False)

    assert to_path.is_file()
    assert not (tmp_path / 'artifacts' / 'app_bins.zip.zip').exists()

    with zipfile.ZipFile(to_path) as zf:
        zip_members = set(zf.namelist())

    assert 'app.bin' in zip_members
    assert 'bootloader/bootloader.bin' in zip_members
    assert 'partition_table/partition-table.bin' in zip_members
    assert 'flasher_args.json' in zip_members
