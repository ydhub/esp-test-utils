import argparse
import shutil
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import esptest.utility.parse_bin_path as parse_bin_path_module
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


def _make_raw_zip(tmp_path: Path, name: str = 'raw_pkg.zip') -> Path:
    pkg = tmp_path / 'raw_pkg'
    pkg.mkdir()
    (pkg / 'fw.bin').write_bytes(b'\xe9' + b'\x00' * 15)
    write_raw_flash(pkg, offset='0x1000', chip='esp32', file='fw.bin')
    zpath = tmp_path / name
    with zipfile.ZipFile(zpath, 'w') as zf:
        for p in pkg.rglob('*'):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(pkg)))
    return zpath


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


def test_prepare_raw_local_zip(tmp_path: Path) -> None:
    zpath = _make_raw_zip(tmp_path)
    parse_bin_path_module.bin_path_to_dir_or_bin.cache_clear()
    path, erase = prepare_download_target(_ns(bin_path=str(zpath), raw=True))
    assert erase is False
    assert (Path(path) / RAW_FLASH_JSON).is_file()
    raw = load_raw_flash(Path(path))
    assert raw['offset'] == '0x1000'
    assert raw['chip'] == 'esp32'


def test_prepare_raw_local_zip_not_raw_package(tmp_path: Path) -> None:
    junk = tmp_path / 'junk'
    junk.mkdir()
    (junk / 'a.bin').write_bytes(b'\x00')
    zpath = tmp_path / 'junk.zip'
    with zipfile.ZipFile(zpath, 'w') as zf:
        zf.write(junk / 'a.bin', arcname='a.bin')
    parse_bin_path_module.bin_path_to_dir_or_bin.cache_clear()
    with pytest.raises(SystemExit):
        prepare_download_target(_ns(bin_path=str(zpath), raw=True))


def test_prepare_raw_http_zip(tmp_path: Path) -> None:
    zpath = _make_raw_zip(tmp_path, name='remote_raw.zip')
    url = 'https://example.com/firmware/remote_raw.zip'

    def _fake_download(remote: str, local_filename: str, timeout: object = None, progress: bool = True) -> None:
        assert remote == url
        shutil.copy(str(zpath), local_filename)

    parse_bin_path_module.bin_path_to_dir_or_bin.cache_clear()
    with patch.object(parse_bin_path_module, 'download_file', side_effect=_fake_download):
        path, erase = prepare_download_target(_ns(bin_path=url, raw=True))
    assert erase is False
    assert (Path(path) / RAW_FLASH_JSON).is_file()


def _patch_download(url: str, payload: Path) -> Any:
    def _fake_download(remote: str, local_filename: str, timeout: object = None, progress: bool = True) -> None:
        assert remote == url
        shutil.copy(str(payload), local_filename)

    return patch.object(parse_bin_path_module, 'download_file', side_effect=_fake_download)


def test_prepare_raw_http_bin(tmp_path: Path) -> None:
    src = tmp_path / 'fw.bin'
    src.write_bytes(b'\xe9' + b'\x00' * 31)
    url = 'https://example.com/firmware/fw.bin'
    parse_bin_path_module.bin_path_to_dir_or_bin.cache_clear()
    with _patch_download(url, src):
        path, erase = prepare_download_target(_ns(bin_path=url, raw=True, offset='0x1000', chip='esp32'))
    assert erase is False
    raw = load_raw_flash(Path(path))
    assert raw['offset'] == '0x1000'
    assert raw['chip'] == 'esp32'


def test_prepare_raw_http_bin_requires_offset_chip(tmp_path: Path) -> None:
    src = tmp_path / 'fw.bin'
    src.write_bytes(b'\xe9' + b'\x00' * 31)
    url = 'https://example.com/firmware/fw2.bin'
    parse_bin_path_module.bin_path_to_dir_or_bin.cache_clear()
    with _patch_download(url, src):
        with pytest.raises(SystemExit):
            prepare_download_target(_ns(bin_path=url, raw=True))


def test_prepare_raw_missing_path_exits(tmp_path: Path) -> None:
    parse_bin_path_module.bin_path_to_dir_or_bin.cache_clear()
    with pytest.raises(SystemExit):
        prepare_download_target(_ns(bin_path=str(tmp_path / 'nope'), raw=True))
