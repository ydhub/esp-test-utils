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


def test_copy_bin_to_new_path_respects_copy_elf_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copy_bin_module, 'IDF_PATH', '')

    from_dir = tmp_path / 'build'
    _write_text(from_dir / 'app.bin')
    _write_text(from_dir / 'app.elf')
    _write_text(from_dir / 'bootloader' / 'bootloader.elf')

    no_elf_dir = tmp_path / 'out-no-elf'
    copy_bin_to_new_path(str(from_dir), str(no_elf_dir), copy_elf=False)
    assert (no_elf_dir / 'app.bin').is_file()
    assert not (no_elf_dir / 'app.elf').exists()
    assert not (no_elf_dir / 'bootloader' / 'bootloader.elf').exists()

    with_elf_dir = tmp_path / 'out-with-elf'
    copy_bin_to_new_path(str(from_dir), str(with_elf_dir), copy_elf=True)
    assert (with_elf_dir / 'app.bin').is_file()
    assert (with_elf_dir / 'app.elf').is_file()
    assert (with_elf_dir / 'bootloader' / 'bootloader.elf').is_file()


def test_copy_bin_to_new_path_respects_force_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copy_bin_module, 'IDF_PATH', '')

    from_dir = tmp_path / 'build'
    _write_text(from_dir / 'app.bin', 'new-bin')

    to_dir = tmp_path / 'out'
    _write_text(to_dir / 'keep.txt', 'keep')
    copy_bin_to_new_path(str(from_dir), str(to_dir), force=False, copy_elf=False)
    assert (to_dir / 'app.bin').is_file()
    assert (to_dir / 'keep.txt').is_file()

    _write_text(to_dir / 'remove-me.txt', 'old')
    copy_bin_to_new_path(str(from_dir), str(to_dir), force=True, copy_elf=False)
    assert (to_dir / 'app.bin').is_file()
    assert not (to_dir / 'remove-me.txt').exists()


def test_copy_bin_to_new_path_supports_extra_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copy_bin_module, 'IDF_PATH', '')

    from_dir = tmp_path / 'build'
    _write_text(from_dir / 'app.bin')
    _write_text(from_dir / 'custom' / 'report.log', 'log')
    _write_text(from_dir / 'custom' / 'meta' / 'manifest.txt', 'manifest')

    to_dir = tmp_path / 'out-extra'
    copy_bin_to_new_path(
        str(from_dir),
        str(to_dir),
        copy_elf=False,
        extra_files=['custom/*.log', 'custom/meta/*.txt'],
    )

    assert (to_dir / 'app.bin').is_file()
    assert (to_dir / 'custom' / 'report.log').is_file()
    assert (to_dir / 'custom' / 'meta' / 'manifest.txt').is_file()
