import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import esptool
import pytest
from esptool.bin_image import LoadFirmwareImage
from packaging.version import Version

import esptest.utility.parse_bin_path as parse_bin_path_module
from esptest.all import DutConfig
from esptest.common.compat_typing import Generator, List, Tuple
from esptest.utility.merged_bin import probe_merged_bin
from esptest.utility.parse_bin_path import (
    ParseBinPath,
    SDKConfig,
    bin_path_to_dir,
    bin_path_to_dir_or_bin,
    get_baud_from_bin_path,
)

TEST_FILE_PATH = Path(__file__).parent / '_files'


@pytest.fixture()
def test_bin_path() -> Generator[Path, None, None]:
    # removed sdkconfig, keep sdkconfig.json
    bin_path = TEST_FILE_PATH / 'test-bin'
    with zipfile.ZipFile(TEST_FILE_PATH / 'test-bin.zip', 'r') as zip_ref:
        zip_ref.extractall(bin_path)
    yield bin_path
    shutil.rmtree(bin_path)


def test_dut_config_baudrate(test_bin_path: Path) -> None:
    dut_config = DutConfig(name='DUT1', baudrate=123456, bin_path=test_bin_path)
    assert dut_config.baudrate == 921600
    dut_config = DutConfig(name='DUT1', baudrate=123456, baudrate_from_bin_path=False, bin_path=test_bin_path)
    assert dut_config.baudrate == 123456
    dut_config = DutConfig(name='DUT1', baudrate=0)
    assert dut_config.baudrate == 115200
    dut_config = DutConfig(name='DUT1', baudrate=0, baudrate_from_bin_path=False, bin_path=test_bin_path)
    assert dut_config.baudrate == 115200


def test_get_baud_from_bin_path(test_bin_path: Path) -> None:
    # test no input
    assert get_baud_from_bin_path('') == 0
    # test invalid bin_path
    no_such_dir = TEST_FILE_PATH / 'not-exist-dir-uiewr7c'
    assert get_baud_from_bin_path(no_such_dir) == 0
    # test bin_path with sdkconfig
    fake_at_bin_path = TEST_FILE_PATH / 'test-get-baud' / 'ESP32AT-V4.1.1.0'
    baud = get_baud_from_bin_path(fake_at_bin_path)
    assert baud == 115200
    # test bin_path with sdkconfig.json
    baud = get_baud_from_bin_path(test_bin_path)
    assert baud == 921600
    # invalid sdkconfig files
    os.remove(str(test_bin_path / 'config' / 'sdkconfig.json'))
    baud = get_baud_from_bin_path(test_bin_path)
    assert baud == 0
    with open(str(test_bin_path / 'config' / 'sdkconfig.json'), 'w') as f:
        f.write(r'{"AAA": 1}')
    baud = get_baud_from_bin_path(test_bin_path)
    assert baud == 0


def test_get_baud_from_bin_path_fallback_checks_both_sdkconfig_paths(tmp_path: Path) -> None:
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    (config_dir / 'sdkconfig.json').write_text('{"ESPTOOLPY_MONITOR_BAUD": 460800}', encoding='utf-8')
    (tmp_path / 'sdkconfig').write_text('CONFIG_CONSOLE_UART_BAUDRATE=115200\n', encoding='utf-8')

    # This non-standard directory has no merged bin, so ParseBinPath raises ValueError.
    assert get_baud_from_bin_path(tmp_path) == 460800

    (config_dir / 'sdkconfig.json').unlink()
    assert get_baud_from_bin_path(tmp_path) == 115200


def test_sdkconfig(test_bin_path: Path) -> None:
    # test loading JSON config
    json_config = test_bin_path / 'config' / 'sdkconfig.json'
    sdk_config = SDKConfig.from_file(json_config)
    assert sdk_config['IDF_TARGET'] == 'esp32c5'  # str
    assert sdk_config['ESPTOOLPY_NO_STUB'] is True  # bool
    assert sdk_config['ESPTOOLPY_MONITOR_BAUD'] == 921600  # int
    assert sdk_config.console_baud == 921600
    assert sdk_config.flash_encryption is False

    # test loading text sdkconfig
    text_config = TEST_FILE_PATH / 'test-get-baud' / 'ESP32AT-V4.1.1.0' / 'sdkconfig'
    sdk_config = SDKConfig.from_file(text_config)
    assert sdk_config['ESPTOOLPY_FLASHSIZE'] == '4MB'  # str
    assert sdk_config['CONSOLE_UART_BAUDRATE'] == 115200  # int
    assert sdk_config['ESPTOOLPY_NO_STUB'] is False  # bool
    assert sdk_config['ESPTOOLPY_FLASHSIZE_4MB'] is True  # bool
    assert sdk_config.console_baud == 115200
    assert sdk_config.flash_encryption is True

    # test file not found
    with pytest.raises(FileNotFoundError):
        SDKConfig.from_file('non_existent_file')

    empty_config = SDKConfig()
    with pytest.raises(AssertionError):
        _ = empty_config.console_baud
    with pytest.raises(AssertionError):
        _ = empty_config.flash_encryption


def test_parse_bin_path(test_bin_path: Path) -> None:
    parse_bin_path = ParseBinPath(test_bin_path)
    assert parse_bin_path.chip == 'esp32c5'
    assert parse_bin_path.stub is False
    assert parse_bin_path.sdkconfig['IDF_TARGET'] == 'esp32c5'
    partitions = parse_bin_path.parse_partitions()
    assert len(partitions) == 6
    assert set([p.name for p in partitions]) == set(['nvs', 'phy_init', 'factory', 'wpa2_cer', 'wpa2_key', 'wpa2_ca'])
    assert partitions[0].name == 'nvs'
    assert partitions[0].offset == '0x9000'
    assert partitions[0].size == 24 * 1024
    flash_args = parse_bin_path.flash_bin_args()
    assert flash_args[:15] == [
        '--chip',
        'esp32c5',
        '--before',
        'default_reset',
        '--after',
        'hard_reset',
        '--no-stub',
        'write_flash',
        '--flash_mode',
        'dio',
        '--flash_size',
        '2MB',
        '--flash_freq',
        '80m',
        '0x2000',
    ]
    nvs_bin = flash_args[-1]
    with open(nvs_bin, 'rb') as f:
        nvs_data = f.read()
        assert len(nvs_data) == 24 * 1024
        assert nvs_data == b'\xff' * 24 * 1024


def test_parse_bin_gen_part(test_bin_path: Path) -> None:
    partition_file = test_bin_path / 'partition_table' / 'partition-table.csv'
    os.remove(str(partition_file))
    assert not partition_file.is_file()
    parse_bin_path = ParseBinPath(test_bin_path)
    partitions = parse_bin_path.parse_partitions()
    assert partition_file.is_file()
    assert len(partitions) == 6
    assert set([p.name for p in partitions]) == set(['nvs', 'phy_init', 'factory', 'wpa2_cer', 'wpa2_key', 'wpa2_ca'])


def test_parse_partitions_when_partition_table_dir_read_only(test_bin_path: Path) -> None:
    """When partition_table dir is read-only, csv is generated in a tmp path and parse_partitions still works.
    Use mock for os.access instead of real chmod so the test works in CI/Docker and on any filesystem.
    """
    part_dir = test_bin_path / 'partition_table'
    partition_csv = part_dir / 'partition-table.csv'
    partition_bin = part_dir / 'partition-table.bin'
    assert partition_bin.is_file(), 'test data must have partition-table.bin'
    os.remove(str(partition_csv))
    assert not partition_csv.is_file()

    real_access = os.access

    def fake_access(path: Path, mode: int) -> bool:
        if Path(path).resolve() == part_dir.resolve() and mode == os.W_OK:
            return False
        return real_access(path, mode)

    # Patch os.access where it is used (global os module) to avoid AttributeError
    # when 'esptest.utility' is not visible in the test environment.
    with patch('os.access', side_effect=fake_access):
        parser = ParseBinPath(test_bin_path)
        partitions = parser.parse_partitions()

    assert not partition_csv.is_file()  # csv file should not be created to read-only dir
    assert len(partitions) == 6
    assert set(p.name for p in partitions) == {'nvs', 'phy_init', 'factory', 'wpa2_cer', 'wpa2_key', 'wpa2_ca'}
    assert parser.partition_table_csv_path  # attribute should be set
    assert parser.partition_table_csv_path.is_file()


def test_parse_partitions_raises_when_generated_csv_not_found(
    test_bin_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gen_esp32part 执行后 csv 仍未出现时应抛出 FileNotFoundError"""
    partition_file = test_bin_path / 'partition_table' / 'partition-table.csv'
    os.remove(str(partition_file))
    assert not partition_file.is_file()

    monkeypatch.setattr(parse_bin_path_module.subprocess, 'check_call', lambda *args, **kwargs: None)
    monkeypatch.setattr(parse_bin_path_module.time, 'sleep', lambda *_args, **_kwargs: None)

    parser = ParseBinPath(test_bin_path)
    with pytest.raises(FileNotFoundError, match='is not created after 1 second'):
        parser.parse_partitions()


def test_bin_path_to_dir() -> None:
    """bin_path_to_dir resolves zip to a standard package directory (no merged)."""
    bin_path_to_dir_or_bin.cache_clear()
    bin_path = bin_path_to_dir(str(TEST_FILE_PATH / 'test-bin.zip'))
    assert Path(bin_path).is_dir()
    parse_bin_path = ParseBinPath(bin_path)
    assert Path(parse_bin_path.bin_path).parts[-1] == 'test-bin'
    assert parse_bin_path.chip == 'esp32c5'


def _try_esptool_merge_bin(
    addr_data: List[Tuple[int, str]],
    chip: str,
    dest: Path,
    flash_freq: str,
    flash_mode: str,
    flash_size: str,
) -> bool:
    """Call esptool merge_bin with new then older calling conventions.

    Returns True when *dest* was written successfully.
    """
    try:
        from esptool.cmds import merge_bin
    except ImportError:
        return False

    attempts = (
        # esptool v5+: chip as keyword
        lambda: merge_bin(
            addr_data,
            chip=chip,
            output=str(dest),
            flash_freq=flash_freq,
            flash_mode=flash_mode,
            flash_size=flash_size,
            format='raw',
        ),
        # chip positional (still v5-style)
        lambda: merge_bin(
            addr_data,
            chip,
            str(dest),
            flash_freq,
            flash_mode,
            flash_size,
            'raw',
        ),
        # older API without chip=
        lambda: merge_bin(
            addr_data,
            output=str(dest),
            flash_freq=flash_freq,
            flash_mode=flash_mode,
            flash_size=flash_size,
            format='raw',
        ),
    )
    for attempt in attempts:
        try:
            attempt()
        except TypeError:
            continue
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            continue
        if dest.is_file() and dest.stat().st_size > 0:
            return True
    return False


def _merge_test_bin(test_bin_path: Path, dest: Path) -> Path:
    """Build a raw merged.bin from the unzipped test-bin fixture.

    Prefer esptool.cmds.merge_bin (new kwargs, then older signatures). Fall back
    to a local 0xFF-padded merge when merge_bin is unavailable or incompatible.
    """
    # The fixture's test.bin is placeholder text. Use its valid bootloader image
    # as a minimal ESP image stub so merged-bin probing can verify app magic.
    shutil.copyfile(
        str(test_bin_path / 'bootloader' / 'bootloader.bin'),
        str(test_bin_path / 'test.bin'),
    )
    with open(str(test_bin_path / 'flasher_args.json'), 'r', encoding='utf-8') as f:
        fa = json.load(f)
    addr_data = [(int(off, 16), str(test_bin_path / rel)) for off, rel in fa['flash_files'].items()]
    chip = fa['extra_esptool_args']['chip']
    flash_freq = fa['flash_settings']['flash_freq']
    flash_mode = fa['flash_settings']['flash_mode']
    flash_size = fa['flash_settings']['flash_size']
    if _try_esptool_merge_bin(addr_data, chip, dest, flash_freq, flash_mode, flash_size):
        try:
            probe_merged_bin(dest)
            return dest
        except ValueError:
            # Older esptool merge_bin may rewrite headers for unsupported chips.
            if dest.is_file():
                dest.unlink()

    segments = []
    for off, rel in fa['flash_files'].items():
        data = (test_bin_path / rel).read_bytes()
        segments.append((int(off, 16), data))
    segments.sort(key=lambda item: item[0])
    end = max(offset + len(data) for offset, data in segments)
    merged = bytearray(b'\xff' * end)
    for offset, data in segments:
        merged[offset : offset + len(data)] = data
    dest.write_bytes(merged)
    return dest


@pytest.fixture()
def merged_bin_file(test_bin_path: Path, tmp_path: Path) -> Path:
    return _merge_test_bin(test_bin_path, tmp_path / 'merged.bin')


def test_bin_path_to_dir_rejects_merged_bin(merged_bin_file: Path) -> None:
    """bin_path_to_dir does not keep a bare .bin path (allow_merged=False)."""
    bin_path_to_dir_or_bin.cache_clear()
    with pytest.raises(ValueError, match='allow_merged=True'):
        bin_path_to_dir(str(merged_bin_file))


def test_bin_path_to_dir_or_bin_keeps_merged_bin(merged_bin_file: Path) -> None:
    """bin_path_to_dir_or_bin with allow_merged=True returns the .bin path."""
    bin_path_to_dir_or_bin.cache_clear()
    resolved = bin_path_to_dir_or_bin(str(merged_bin_file), allow_merged=True, check_valid=True)
    assert Path(resolved).resolve() == merged_bin_file.resolve()
    assert Path(resolved).is_file()


def test_bin_path_to_dir_or_bin_http_merged_bin(merged_bin_file: Path) -> None:
    """http(s) .bin is downloaded; allow_merged=True keeps the file after check_valid."""
    url = 'https://example.com/firmware/merged.bin'

    def _fake_download(remote: str, local_filename: str, timeout: object = None, progress: bool = True) -> None:
        assert remote == url
        shutil.copy(str(merged_bin_file), local_filename)

    bin_path_to_dir_or_bin.cache_clear()
    with patch.object(parse_bin_path_module, 'download_file', side_effect=_fake_download):
        resolved = bin_path_to_dir_or_bin(url, allow_merged=True, check_valid=True)
        assert Path(resolved).is_file()
        assert Path(resolved).name == 'merged.bin'
        parsed = ParseBinPath(url)
    assert parsed._mode == 'merged'
    assert parsed.chip == 'esp32c5'


def test_bin_path_to_dir_http_merged_bin_rejected(merged_bin_file: Path) -> None:
    """bin_path_to_dir downloads http .bin then rejects keeping it (no merged support)."""
    url = 'https://example.com/firmware/merged.bin'

    def _fake_download(remote: str, local_filename: str, timeout: object = None, progress: bool = True) -> None:
        assert remote == url
        shutil.copy(str(merged_bin_file), local_filename)

    bin_path_to_dir_or_bin.cache_clear()
    with patch.object(parse_bin_path_module, 'download_file', side_effect=_fake_download):
        with pytest.raises(ValueError, match='allow_merged=True'):
            bin_path_to_dir(url)


def test_parse_bin_path_bare_merged_sets_mode(merged_bin_file: Path) -> None:
    parsed = ParseBinPath(merged_bin_file)
    assert parsed._mode == 'merged'
    assert Path(parsed._merged_bin_path).resolve() == merged_bin_file.resolve()
    assert Path(parsed.bin_path).resolve() == merged_bin_file.parent.resolve()


def test_bare_merged_flasher_args_no_missing_file_warning(
    merged_bin_file: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Bare merged under a dir without flasher_args.json must not warn."""
    alone = tmp_path / 'bare'
    alone.mkdir()
    target = alone / 'merged.bin'
    shutil.copy(str(merged_bin_file), str(target))
    with caplog.at_level(logging.WARNING, logger='parse_bin_path'):
        parsed = ParseBinPath(target)
        assert parsed.chip == 'esp32c5'
        _ = parsed.flasher_args
    assert 'flasher_args.json' not in caplog.text


def test_merged_parse_partitions_and_nvs(merged_bin_file: Path) -> None:
    parsed = ParseBinPath(merged_bin_file)
    parts = parsed.parse_partitions()
    names = {p.name for p in parts}
    assert 'nvs' in names
    nvs = parsed.get_partition_info('nvs')
    assert nvs.offset == '0x9000'
    assert nvs.size == 24 * 1024
    assert parsed.chip == 'esp32c5'


def test_merged_flash_bin_args_zero_offset(merged_bin_file: Path) -> None:
    parsed = ParseBinPath(merged_bin_file)
    args = parsed.flash_bin_args(erase_nvs=True)
    assert 'write_flash' in args
    idx = args.index('0x0')
    assert Path(args[idx + 1]).resolve() == merged_bin_file.resolve()
    assert '0x9000' in args


def test_merged_flash_bin_args_skips_secure_boot_without_sdkconfig(merged_bin_file: Path, tmp_path: Path) -> None:
    alone = tmp_path / 'nosdk'
    alone.mkdir()
    target = alone / 'merged.bin'
    shutil.copy(str(merged_bin_file), str(target))
    parsed = ParseBinPath(target)
    args = parsed.flash_bin_args(erase_nvs=False, secure_boot=True)
    assert '--force' in args
    assert '0x0' in args


def test_merged_with_sdkconfig_still_checks_secure_boot(
    test_bin_path: Path, merged_bin_file: Path, tmp_path: Path
) -> None:
    with_sdkconfig = tmp_path / 'withsdk'
    with_sdkconfig.mkdir()
    shutil.copy(str(merged_bin_file), str(with_sdkconfig / 'merged.bin'))
    shutil.copytree(str(test_bin_path / 'config'), str(with_sdkconfig / 'config'))
    parsed = ParseBinPath(with_sdkconfig / 'merged.bin')
    with pytest.raises(RuntimeError, match='Secure Boot'):
        parsed.flash_bin_args(erase_nvs=False, secure_boot=True)


def test_parse_bin_path_merged_only_directory(merged_bin_file: Path, tmp_path: Path) -> None:
    alone = tmp_path / 'alone'
    alone.mkdir()
    target = alone / 'firmware.bin'
    shutil.copy(str(merged_bin_file), str(target))
    parsed = ParseBinPath(alone)
    assert parsed._mode == 'merged'
    assert Path(parsed._merged_bin_path).name == 'firmware.bin'


def test_parse_bin_path_standard_dir_unchanged(test_bin_path: Path) -> None:
    parsed = ParseBinPath(test_bin_path)
    assert parsed._mode == 'standard'
    assert parsed.chip == 'esp32c5'


def test_parse_bin_path_two_merged_bins_raise(merged_bin_file: Path, tmp_path: Path) -> None:
    d = tmp_path / 'two'
    d.mkdir()
    shutil.copy(str(merged_bin_file), str(d / 'a.bin'))
    shutil.copy(str(merged_bin_file), str(d / 'b.bin'))
    with pytest.raises(ValueError, match='merged'):
        ParseBinPath(d)


def test_parse_bin_path_rejects_merged_bin_with_invalid_app_magic(merged_bin_file: Path, tmp_path: Path) -> None:
    invalid = tmp_path / 'invalid'
    invalid.mkdir()
    candidate = invalid / 'firmware.bin'
    shutil.copy(str(merged_bin_file), str(candidate))
    data = bytearray(candidate.read_bytes())
    data[0x10000] = 0
    candidate.write_bytes(data)

    with pytest.raises(ValueError, match='found 0'):
        ParseBinPath(invalid)


def test_probe_merged_bin_passes_path_not_raw_bytes(merged_bin_file: Path) -> None:
    """esptool 4.x rejects raw bytes (no tell()); pass a filesystem path instead."""
    seen = []  # type: List[object]

    def load_like_esptool_v4(chip: str, image_file: object) -> object:
        seen.append(image_file)
        if isinstance(image_file, (bytes, bytearray)):
            # Same failure mode as ESP32FirmwareImage.__init__ on esptool 4.x / py37 CI.
            raise AttributeError("'bytes' object has no attribute 'tell'")
        if not isinstance(image_file, str):
            raise TypeError('expected filesystem path str for esptool 4.x compat')
        return LoadFirmwareImage(chip, image_file)

    with patch('esptool.bin_image.LoadFirmwareImage', side_effect=load_like_esptool_v4):
        meta = probe_merged_bin(merged_bin_file)
    assert meta.chip == 'esp32c5'
    assert meta.boot_offset == 0x2000
    assert seen and isinstance(seen[0], str)


def test_parse_bin_path_standard_markers_broken_flasher_no_merged_fallback(
    test_bin_path: Path, merged_bin_file: Path
) -> None:
    # Keep bootloader/ + partition_table/; add a valid merged at top level; break flasher_args.
    shutil.copy(str(merged_bin_file), str(test_bin_path / 'merged.bin'))
    (test_bin_path / 'flasher_args.json').write_text('{not-json', encoding='utf-8')
    parsed = ParseBinPath(test_bin_path)
    assert parsed._mode == 'standard'
    # Accessing chip / flash must fail in standard path (empty/invalid flasher_args), not switch mode.
    with pytest.raises((KeyError, TypeError, ValueError, json.JSONDecodeError)):
        _ = parsed.flash_bin_args(erase_nvs=False)


def test_flash_partition_args_with_bin_files(test_bin_path: Path, tmp_path: Path) -> None:
    """flash_partition_args 应拼接各分区的 offset 与 bin 路径（write_flash 公共前缀与 flash_bin_args 一致）。"""
    parse_bin_path = ParseBinPath(test_bin_path)
    factory_bin = tmp_path / 'factory.bin'
    factory_bin.write_bytes(b'\x00\x01\x02')
    args = parse_bin_path.flash_partition_args({'factory': str(factory_bin)})
    assert args[:14] == [
        '--chip',
        'esp32c5',
        '--before',
        'default_reset',
        '--after',
        'hard_reset',
        '--no-stub',
        'write_flash',
        '--flash_mode',
        'dio',
        '--flash_size',
        '2MB',
        '--flash_freq',
        '80m',
    ]
    assert args[-2] == '0x10000'
    assert args[-1] == str(factory_bin)


def test_flash_partition_args_nvs_empty_generates_erase_bin(
    test_bin_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nvs 传入空字符串时应生成全 0xff 的临时 bin（与 erase nvs 语义一致）。"""
    out = tmp_path / 'nvs_erase.bin'

    def _fake_mktemp() -> str:
        return str(out)

    # 使用模块对象 patch，避免 pytest 对长点号路径 resolve 时在个别环境下误解析
    monkeypatch.setattr(parse_bin_path_module.tempfile, 'mktemp', _fake_mktemp)
    parse_bin_path = ParseBinPath(test_bin_path)
    args = parse_bin_path.flash_partition_args({'nvs': ''})
    assert out.is_file()
    assert out.read_bytes() == b'\xff' * (24 * 1024)
    assert args[-2] == '0x9000'
    assert args[-1] == str(out)


def test_flash_partition_args_missing_file_raises(test_bin_path: Path) -> None:
    parse_bin_path = ParseBinPath(test_bin_path)
    with pytest.raises(ValueError, match='Can not find or open partition bin file'):
        parse_bin_path.flash_partition_args({'factory': '/no/such/partition.bin'})


def test_flash_partition_args_unknown_partition_raises(test_bin_path: Path, tmp_path: Path) -> None:
    parse_bin_path = ParseBinPath(test_bin_path)
    dummy = tmp_path / 'x.bin'
    dummy.write_bytes(b'\x00')
    with pytest.raises(ValueError, match='Can not find no_such_part partition info'):
        parse_bin_path.flash_partition_args({'no_such_part': str(dummy)})


def test_get_supported_chip_rev_range_from_bootloader(test_bin_path: Path) -> None:
    parsed = ParseBinPath(test_bin_path)
    image = MagicMock()
    image.min_rev_full = 100
    image.max_rev_full = 199
    with patch(
        'esptool.bin_image.LoadFirmwareImage',
        return_value=image,
    ) as load_image:
        assert parsed.get_supported_chip_rev_range() == (100, 199)
    load_image.assert_called_once()
    args, _kwargs = load_image.call_args
    assert args[0] == 'esp32c5'
    assert Path(args[1]).parts[-2:] == ('bootloader', 'bootloader.bin')


@pytest.mark.skipif(
    Version(esptool.__version__) < Version('4.8'),
    reason='esptool < 4.8 LoadFirmwareImage does not support esp32c5',
)
def test_merged_get_supported_chip_rev_range_from_bootloader_slice(test_bin_path: Path, merged_bin_file: Path) -> None:
    boot_path = str(test_bin_path / 'bootloader' / 'bootloader.bin')
    image = LoadFirmwareImage('esp32c5', boot_path)
    expected = (int(image.min_rev_full), int(image.max_rev_full))
    assert expected == (100, 199)

    parsed = ParseBinPath(merged_bin_file)
    assert parsed.get_supported_chip_rev_range() == expected


def test_merged_get_supported_chip_rev_range_fallback_sdkconfig(
    test_bin_path: Path, merged_bin_file: Path, tmp_path: Path
) -> None:
    d = tmp_path / 'rev_fb'
    d.mkdir()
    shutil.copy(str(merged_bin_file), str(d / 'merged.bin'))
    shutil.copytree(str(test_bin_path / 'config'), str(d / 'config'))
    parsed = ParseBinPath(d / 'merged.bin')
    with patch.object(ParseBinPath, '_rev_range_from_bootloader', side_effect=ValueError('boom')):
        assert parsed.get_supported_chip_rev_range() == (100, 199)


def test_get_supported_chip_rev_range_chip_override(test_bin_path: Path) -> None:
    parsed = ParseBinPath(test_bin_path)
    image = MagicMock()
    image.min_rev_full = 0
    image.max_rev_full = 99
    with patch(
        'esptool.bin_image.LoadFirmwareImage',
        return_value=image,
    ) as load_image:
        assert parsed.get_supported_chip_rev_range(chip='esp32') == (0, 99)
    assert load_image.call_args[0][0] == 'esp32'


def test_get_supported_chip_rev_range_fallback_sdkconfig(test_bin_path: Path) -> None:
    parsed = ParseBinPath(test_bin_path)
    with patch(
        'esptool.bin_image.LoadFirmwareImage',
        side_effect=RuntimeError('boom'),
    ):
        assert parsed.get_supported_chip_rev_range() == (100, 199)


def test_get_supported_chip_rev_range_both_fail(test_bin_path: Path) -> None:
    parsed = ParseBinPath(test_bin_path)
    # Remove FULL keys so sdkconfig fallback fails
    for key in list(parsed.sdkconfig.keys()):
        if key.endswith('_REV_MIN_FULL') or key.endswith('_REV_MAX_FULL'):
            if 'EFUSE_BLOCK' in key:
                continue
            del parsed.sdkconfig[key]
    with patch(
        'esptool.bin_image.LoadFirmwareImage',
        side_effect=RuntimeError('boom'),
    ):
        with pytest.raises(ValueError, match='failed to get supported chip rev range'):
            parsed.get_supported_chip_rev_range()


def test_dump_nvs_args(test_bin_path: Path, tmp_path: Path) -> None:
    parse_bin_path = ParseBinPath(test_bin_path)
    out = tmp_path / 'nvs_dump.bin'
    args = parse_bin_path.dump_nvs_args(str(out))
    assert args[:7] == [
        '--chip',
        'esp32c5',
        '--before',
        'default_reset',
        '--after',
        'hard_reset',
        '--no-stub',
    ]
    assert args[7:11] == ['read_flash', '0x9000', str(24 * 1024), str(out)]


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
    # manual tests
    # baud = get_baud_from_bin_path('/NFS/wx_test_bin/ESP32_AT_OTA/wroom/ESP32-WROOM-32-AT-V4.1.1.0/AT')
    # assert baud == 115200
