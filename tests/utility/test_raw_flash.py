import json
from pathlib import Path

import pytest

from esptest.utility.raw_flash import (
    RAW_FLASH_JSON,
    apply_raw_overrides,
    is_raw_bin_dir,
    load_raw_flash,
    materialize_raw_dir,
    raw_to_flasher_args,
    write_raw_flash,
)


def test_is_raw_bin_dir(tmp_path: Path) -> None:
    assert is_raw_bin_dir(tmp_path) is False
    (tmp_path / RAW_FLASH_JSON).write_text('{}', encoding='utf-8')
    assert is_raw_bin_dir(tmp_path) is True


def test_write_and_load_raw_flash(tmp_path: Path) -> None:
    (tmp_path / 'fw.bin').write_bytes(b'\xe9' + b'\x00' * 15)
    write_raw_flash(tmp_path, offset='0x1000', chip='esp32', file='fw.bin')
    raw = load_raw_flash(tmp_path)
    assert raw['offset'] == '0x1000'
    assert raw['chip'] == 'esp32'
    assert raw['file'] == 'fw.bin'
    assert raw['write_flash_args'][0] == '--flash_mode'


def test_load_raw_flash_missing_fields(tmp_path: Path) -> None:
    (tmp_path / RAW_FLASH_JSON).write_text(json.dumps({'offset': '0x1000'}), encoding='utf-8')
    with pytest.raises(ValueError, match='chip|file'):
        load_raw_flash(tmp_path)


def test_materialize_raw_dir(tmp_path: Path) -> None:
    src = tmp_path / 'ESP32_RF.bin'
    src.write_bytes(b'\xe9' + b'\x00' * 31)
    pkg = Path(materialize_raw_dir(str(src), offset='0x1000', chip='esp32', parent_dir=str(tmp_path / 'out')))
    assert (pkg / RAW_FLASH_JSON).is_file()
    assert (pkg / 'ESP32_RF.bin').is_file()
    raw = load_raw_flash(pkg)
    assert raw['file'] == 'ESP32_RF.bin'
    assert raw['offset'] == '0x1000'
    assert raw['chip'] == 'esp32'


def test_raw_to_flasher_args() -> None:
    fa = raw_to_flasher_args(
        {
            'offset': '0x1000',
            'chip': 'esp32',
            'file': 'fw.bin',
            'write_flash_args': ['--flash_mode', 'dio', '--flash_freq', '40m', '--flash_size', 'detect'],
        }
    )
    assert fa['flash_files'] == {'0x1000': 'fw.bin'}
    assert fa['extra_esptool_args']['chip'] == 'esp32'
    assert fa['extra_esptool_args']['before'] == 'default_reset'
    assert fa['extra_esptool_args']['after'] == 'hard_reset'
    assert fa['extra_esptool_args']['stub'] is True


def test_apply_raw_overrides() -> None:
    raw = {'offset': '0x1000', 'chip': 'esp32', 'file': 'fw.bin'}
    out = apply_raw_overrides(raw, offset='0x2000', chip='esp32s3')
    assert out['offset'] == '0x2000'
    assert out['chip'] == 'esp32s3'
    assert raw['offset'] == '0x1000'  # original unchanged
