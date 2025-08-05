import os
import shutil
import zipfile
from pathlib import Path

import pytest

from esptest.all import DutConfig
from esptest.common.compat_typing import Generator
from esptest.utility.parse_bin_path import ParseBinPath, SDKConfig, get_baud_from_bin_path

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


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
    # manual tests
    # baud = get_baud_from_bin_path('/NFS/wx_test_bin/ESP32_AT_OTA/wroom/ESP32-WROOM-32-AT-V4.1.1.0/AT')
    # assert baud == 115200
