import os
import shutil
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

import esptest.utility.parse_bin_path as parse_bin_path_module
from esptest.all import DutConfig
from esptest.common.compat_typing import Generator
from esptest.utility.parse_bin_path import ParseBinPath, SDKConfig, bin_path_to_dir, get_baud_from_bin_path

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


def test_bin_path_to_dir() -> None:
    bin_path = bin_path_to_dir(str(TEST_FILE_PATH / 'test-bin.zip'))
    parse_bin_path = ParseBinPath(bin_path)
    assert Path(parse_bin_path.bin_path).parts[-1] == 'test-bin'
    assert parse_bin_path.chip == 'esp32c5'


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


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
    # manual tests
    # baud = get_baud_from_bin_path('/NFS/wx_test_bin/ESP32_AT_OTA/wroom/ESP32-WROOM-32-AT-V4.1.1.0/AT')
    # assert baud == 115200
