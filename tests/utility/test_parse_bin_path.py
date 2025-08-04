import shutil
import zipfile
from pathlib import Path

import pytest

from esptest.common.compat_typing import Generator
from esptest.utility.parse_bin_path import ParseBinPath, get_baud_from_bin_path

TEST_FILE_PATH = Path(__file__).parent / '_files'


@pytest.fixture()
def test_bin_path() -> Generator[Path, None, None]:
    # removed sdkconfig, keep sdkconfig.json
    bin_path = TEST_FILE_PATH / 'test-bin'
    with zipfile.ZipFile(TEST_FILE_PATH / 'test-bin.zip', 'r') as zip_ref:
        zip_ref.extractall(bin_path)
    yield bin_path
    shutil.rmtree(bin_path)


def test_get_baud_from_bin_path() -> None:
    # test no input
    baud = get_baud_from_bin_path('')
    assert baud == 0
    # test invalid bin_path
    no_such_dir = TEST_FILE_PATH / 'not-exist-dir-uiewr7c'
    with pytest.raises(OSError):
        _ = get_baud_from_bin_path(no_such_dir)
    # test bin_path with sdkconfig
    fake_at_bin_path = TEST_FILE_PATH / 'test-get-baud' / 'ESP32AT-V4.1.1.0'
    baud = get_baud_from_bin_path(fake_at_bin_path)
    assert baud == 115200


def test_parse_bin_path(test_bin_path: Path) -> None:
    baud = get_baud_from_bin_path(test_bin_path)
    assert baud == 921600
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
