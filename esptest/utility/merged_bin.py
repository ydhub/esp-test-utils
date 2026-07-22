"""Helpers for detecting and probing ESP-IDF raw merged bin images."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import esptest.common.compat_typing as t

from .gen_esp32part import (  # type: ignore[attr-defined]  # pylint: disable=relative-beyond-top-level
    SUBTYPES,
    TYPES,
    PartitionTable,
)

ESP_IMAGE_MAGIC = 0xE9
PART_MAGIC = b'\xaa\x50'
COMMON_BOOT_OFFSETS = (0x0, 0x1000, 0x2000)
COMMON_PART_OFFSETS = (0x8000, 0x9000)

# Fallback when esptool has no CHIP_DEFS (older releases) or lacks a target entry.
_IMAGE_CHIP_ID_FALLBACK = {
    0: 'esp32',
    2: 'esp32s2',
    4: 'esp8266',
    5: 'esp32c3',
    6: 'esp32h2',
    7: 'esp32c2',
    9: 'esp32s3',
    12: 'esp32c6',
    13: 'esp32c61',
    16: 'esp32h21',
    17: 'esp32p4',
    18: 'esp32h4',
    23: 'esp32c5',
}


@dataclass
class PartitionInfo:
    name: str
    type: str
    subtype: str
    offset: str
    size: int
    flags: str


@dataclass
class MergedBinMeta:
    boot_offset: int
    part_offset: int
    chip: str
    partitions: t.List[PartitionInfo]


def chip_name_from_image_chip_id(chip_id: int) -> str:
    try:
        from esptool import CHIP_DEFS
    except ImportError:
        CHIP_DEFS = {}

    for name, cls in CHIP_DEFS.items():
        if getattr(cls, 'IMAGE_CHIP_ID', None) == chip_id:
            return str(name)
    if chip_id in _IMAGE_CHIP_ID_FALLBACK:
        return _IMAGE_CHIP_ID_FALLBACK[chip_id]
    raise ValueError(f'unknown IMAGE_CHIP_ID: {chip_id!r}')


def is_standard_bin_dir(path: Path) -> bool:
    """True when directory looks like an IDF flash package."""
    return (path / 'bootloader').is_dir() and (path / 'partition_table').is_dir()


def _read_u8(data: bytes, offset: int) -> t.Optional[int]:
    if offset < 0 or offset >= len(data):
        return None
    return data[offset]


def _partition_infos_from_table(table: t.Any) -> t.List[PartitionInfo]:
    type_names = {value: name for name, value in TYPES.items()}
    partitions = []
    for part in table:
        type_name = type_names.get(part.type, str(part.type))
        subtype_names = {value: name for name, value in SUBTYPES.get(part.type, {}).items()}
        subtype_name = subtype_names.get(part.subtype, str(part.subtype))
        partitions.append(PartitionInfo(part.name, type_name, subtype_name, hex(int(part.offset)), int(part.size), ''))
    return partitions


def _load_boot_firmware_image(chip: str, boot_image: bytes) -> t.Any:
    """Load bootloader image via esptool using a temp file path.

    esptool 4.x rejects raw bytes (needs path/file-like with tell()).
    esptool 5.x accepts bytes but rejects BytesIO without a ``name``.
    A temp file path works on both.
    """
    from esptool.bin_image import LoadFirmwareImage

    tmp_path = ''
    try:
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(boot_image)
        return LoadFirmwareImage(chip, tmp_path)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def probe_merged_bin(path: Path) -> MergedBinMeta:
    """Validate a raw merged .bin and return boot/partition/chip metadata."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f'failed to read merged bin {path}: {exc}') from exc

    part_offset = None
    partition_table = None
    for offset in COMMON_PART_OFFSETS:
        if data[offset : offset + 2] != PART_MAGIC:
            continue
        try:
            parsed_table = PartitionTable.from_binary(data[offset : offset + 0x1000])
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            continue
        if parsed_table:
            part_offset = offset
            partition_table = parsed_table
            break
    if part_offset is None or partition_table is None:
        raise ValueError(f'merged bin has no valid partition table: {path}')

    boot_offset = None
    for offset in COMMON_BOOT_OFFSETS:
        if _read_u8(data, offset) == ESP_IMAGE_MAGIC:
            boot_offset = offset
            break
    if boot_offset is None:
        raise ValueError(f'merged bin has no bootloader image: {path}')

    partitions = _partition_infos_from_table(partition_table)
    app_partitions = [part for part in partitions if part.type == 'app']
    if not any(_read_u8(data, int(part.offset, 16)) == ESP_IMAGE_MAGIC for part in app_partitions):
        raise ValueError(f'merged bin has no valid app image: {path}')

    image_end = min(len(data), boot_offset + 0x10000)
    if part_offset > boot_offset:
        image_end = min(image_end, part_offset)
    boot_image = data[boot_offset:image_end]
    if len(boot_image) < 14:
        raise ValueError(f'merged bin bootloader chip could not be identified: {path}')
    chip_id = int.from_bytes(boot_image[12:14], byteorder='little')
    chip = chip_name_from_image_chip_id(chip_id)
    try:
        image = _load_boot_firmware_image(chip, boot_image)
    except KeyError:
        # Older esptool: IMAGE_CHIP_ID known but no firmware image class for this SoC.
        return MergedBinMeta(boot_offset, part_offset, chip, partitions)
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        raise ValueError(f'merged bin has invalid bootloader image: {path}') from exc
    if chip_name_from_image_chip_id(int(image.chip_id)) != chip:
        raise ValueError(f'merged bin bootloader chip could not be identified: {path}')

    return MergedBinMeta(boot_offset, part_offset, chip, partitions)


def find_merged_bin_in_dir(dir_path: Path) -> Path:
    """Return the single valid top-level merged .bin in *dir_path*."""
    candidates = []
    for path in sorted(dir_path.iterdir()):
        if path.is_file() and path.suffix.lower() == '.bin':
            try:
                probe_merged_bin(path)
                candidates.append(path)
            except ValueError:
                continue
    if len(candidates) != 1:
        raise ValueError(f'expected exactly one valid merged .bin in {dir_path}, found {len(candidates)}')
    return candidates[0]


def synthetic_flasher_args(meta: MergedBinMeta) -> t.Dict[str, t.Any]:
    """Minimal flasher_args-compatible dict for a probed merged bin."""
    return {
        'write_flash_args': ['--flash_mode', 'keep', '--flash_size', 'keep', '--flash_freq', 'keep'],
        'flash_files': {'0x0': '<filled by flash_bin_args, not used>'},
        'bootloader': {'offset': hex(meta.boot_offset), 'file': ''},
        'extra_esptool_args': {
            'after': 'hard_reset',
            'before': 'default_reset',
            'stub': True,
            'chip': meta.chip,
        },
    }
