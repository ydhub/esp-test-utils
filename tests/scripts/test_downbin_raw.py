import argparse
from pathlib import Path
from typing import Any

import pytest

from esptest.scripts.downbin import prepare_download_target
from esptest.utility.raw_flash import RAW_FLASH_JSON, load_raw_flash, write_raw_flash


def _ns(**kwargs: Any) -> argparse.Namespace:
    defaults = dict(
        bin_path=None,
        merged=False,
        raw=False,
        offset=None,
        chip=None,
        erase_nvs=True,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_prepare_raw_bin_materializes(tmp_path: Path) -> None:
    src = tmp_path / 'rf.bin'
    src.write_bytes(b'\xe9' + b'\x00' * 31)
    path, erase = prepare_download_target(_ns(bin_path=str(src), raw=True, offset='0x1000', chip='esp32'))
    assert erase is False
    assert (Path(path) / RAW_FLASH_JSON).is_file()
    raw = load_raw_flash(Path(path))
    assert raw['offset'] == '0x1000'
    assert raw['chip'] == 'esp32'


def test_prepare_raw_dir(tmp_path: Path) -> None:
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / 'fw.bin').write_bytes(b'\xe9' + b'\x00' * 15)
    write_raw_flash(pkg, offset='0x1000', chip='esp32', file='fw.bin')
    path, erase = prepare_download_target(_ns(bin_path=str(pkg), raw=True))
    assert Path(path).resolve() == pkg.resolve()
    assert erase is False


def test_prepare_raw_dir_overrides(tmp_path: Path) -> None:
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    (pkg / 'fw.bin').write_bytes(b'\xe9' + b'\x00' * 15)
    write_raw_flash(pkg, offset='0x1000', chip='esp32', file='fw.bin')
    path, erase = prepare_download_target(_ns(bin_path=str(pkg), raw=True, offset='0x2000', chip='esp32s3'))
    raw = load_raw_flash(Path(path))
    assert raw['offset'] == '0x2000'
    assert raw['chip'] == 'esp32s3'
    assert erase is False
    assert Path(path).resolve() != pkg.resolve()


def test_prepare_raw_and_merged_mutex() -> None:
    with pytest.raises(SystemExit):
        prepare_download_target(_ns(bin_path='x.bin', raw=True, merged=True, offset='0x1000', chip='esp32'))


def test_prepare_raw_bin_requires_offset_chip(tmp_path: Path) -> None:
    src = tmp_path / 'rf.bin'
    src.write_bytes(b'\xe9\x00')
    with pytest.raises(SystemExit):
        prepare_download_target(_ns(bin_path=str(src), raw=True, chip='esp32'))
    with pytest.raises(SystemExit):
        prepare_download_target(_ns(bin_path=str(src), raw=True, offset='0x1000'))
