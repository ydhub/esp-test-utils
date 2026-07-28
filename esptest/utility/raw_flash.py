"""Helpers for raw (offset-based) flash packages marked by raw_flash.json."""

import json
import shutil
import tempfile
from pathlib import Path

import esptest.common.compat_typing as t

RAW_FLASH_JSON = 'raw_flash.json'
DEFAULT_WRITE_FLASH_ARGS = ['--flash_mode', 'dio', '--flash_freq', '40m', '--flash_size', 'detect']
_REQUIRED = ('offset', 'chip', 'file')


def is_raw_bin_dir(path: Path) -> bool:
    return path.is_dir() and (path / RAW_FLASH_JSON).is_file()


def load_raw_flash(dir_path: Path) -> t.Dict[str, t.Any]:
    marker = dir_path / RAW_FLASH_JSON
    if not marker.is_file():
        raise ValueError(f'missing {RAW_FLASH_JSON} in {dir_path}')
    try:
        with marker.open('r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'invalid {RAW_FLASH_JSON} in {dir_path}: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError(f'{RAW_FLASH_JSON} must be a JSON object: {dir_path}')
    missing = [k for k in _REQUIRED if not data.get(k)]
    if missing:
        raise ValueError(f'{RAW_FLASH_JSON} missing required fields {missing}: {dir_path}')
    bin_file = dir_path / str(data['file'])
    if not bin_file.is_file():
        raise ValueError(f'raw bin file not found: {bin_file}')
    if 'write_flash_args' not in data or not data['write_flash_args']:
        data = dict(data)
        data['write_flash_args'] = list(DEFAULT_WRITE_FLASH_ARGS)
    return data


def write_raw_flash(
    dir_path: Path,
    *,
    offset: str,
    chip: str,
    file: str,
    write_flash_args: t.Optional[t.List[str]] = None,
) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    payload = {
        'offset': offset,
        'chip': chip,
        'file': file,
        'write_flash_args': list(write_flash_args or DEFAULT_WRITE_FLASH_ARGS),
    }
    marker = dir_path / RAW_FLASH_JSON
    with marker.open('w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
        f.write('\n')
    return marker


def materialize_raw_dir(
    bin_path: str,
    *,
    offset: str,
    chip: str,
    parent_dir: t.Optional[str] = None,
) -> str:
    src = Path(bin_path)
    if not src.is_file():
        raise ValueError(f'raw bin path is not a file: {bin_path}')
    if parent_dir:
        pkg = Path(parent_dir)
        pkg.mkdir(parents=True, exist_ok=True)
    else:
        pkg = Path(tempfile.mkdtemp(prefix='raw_bin_'))
    dest_name = src.name
    shutil.copy2(str(src), str(pkg / dest_name))
    write_raw_flash(pkg, offset=offset, chip=chip, file=dest_name)
    return str(pkg.resolve())


def apply_raw_overrides(
    raw: t.Dict[str, t.Any],
    *,
    offset: t.Optional[str] = None,
    chip: t.Optional[str] = None,
) -> t.Dict[str, t.Any]:
    out = dict(raw)
    if offset:
        out['offset'] = offset
    if chip:
        out['chip'] = chip
    return out


def raw_to_flasher_args(raw: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
    write_args = list(raw.get('write_flash_args') or DEFAULT_WRITE_FLASH_ARGS)
    return {
        'write_flash_args': write_args,
        'flash_files': {str(raw['offset']): str(raw['file'])},
        'extra_esptool_args': {
            'chip': str(raw['chip']),
            'stub': True,
            'before': 'default_reset',
            'after': 'hard_reset',
        },
    }
