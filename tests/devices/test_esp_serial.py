from unittest import mock

import esptool
import pytest

from esptest.devices import esp_serial
from esptest.devices.esp_serial import (
    EspPortInfo,
    _chip_name_to_target,
    _get_esp_port_info,
    detect_port_info_no_cache,
    get_available_ports,
    list_all_esp_ports,
)


def test_chip_name_to_target() -> None:
    assert _chip_name_to_target('ESP32') == 'esp32'
    assert _chip_name_to_target('ESP32-S3') == 'esp32s3'
    assert _chip_name_to_target('ESP32-C3') == 'esp32c3'
    # c61 must be matched before c6 (prefix collision)
    assert _chip_name_to_target('ESP32-C6') == 'esp32c6'
    assert _chip_name_to_target('ESP32-C61') == 'esp32c61'
    assert _chip_name_to_target('NOT-A-CHIP') == 'unknown'
    assert _chip_name_to_target('') == 'unknown'


def _make_fake_esp() -> mock.MagicMock:
    esp = mock.MagicMock()
    esp.port = '/dev/ttyUSB0'
    esp.CHIP_NAME = 'ESP32-C3'
    esp.read_mac.return_value = [0x24, 0x6F, 0x28, 0x01, 0x02, 0x03]
    esp.get_chip_description.return_value = 'ESP32-C3 (QFN32) (revision v0.4)'
    esp.get_major_chip_version.return_value = 0
    esp.get_minor_chip_version.return_value = 4
    esp.get_crystal_freq.return_value = 40
    esp.flash_id.return_value = 0x1740EF
    return esp


def test_get_esp_port_info_success() -> None:
    esp = _make_fake_esp()
    # create=True so the patch works even on the older esptool used on Python 3.7,
    # which does not expose attach_flash/detect_flash_size.
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esptool.cmds, 'attach_flash', create=True), \
        mock.patch.object(esptool.cmds, 'detect_flash_size', create=True, return_value='4MB'):
        info = _get_esp_port_info(esp)
    # fmt: on

    assert info['chip_name'] == 'ESP32-C3'
    assert info['mac'] == '24:6f:28:01:02:03'
    assert info['chip_version'] == 'v0.4'
    assert info['chip_xtal'] == '40'
    assert info['flash_id'] == hex(0x1740EF)
    assert info['flash_size'] == '4MB'
    assert info['target'] == 'esp32c3'


def test_get_esp_port_info_partial_failure() -> None:
    """chip_name/target must still be populated when reading details fails."""
    esp = _make_fake_esp()
    esp.read_mac.side_effect = RuntimeError('read mac failed')
    with mock.patch.object(esptool.cmds, 'attach_flash', create=True, side_effect=RuntimeError('no flash')):
        info = _get_esp_port_info(esp)

    assert info['chip_name'] == 'ESP32-C3'
    assert info['target'] == 'esp32c3'
    # details that failed must be absent rather than raising
    assert 'mac' not in info
    assert 'flash_size' not in info


def test_get_esp_port_info_unrecognized_chip_name() -> None:
    esp = _make_fake_esp()
    esp.CHIP_NAME = 'ESP32-FOO'
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esptool.cmds, 'attach_flash', create=True), \
        mock.patch.object(esptool.cmds, 'detect_flash_size', create=True, return_value='4MB'):
        info = _get_esp_port_info(esp)
    # fmt: on
    assert info['chip_name'] == 'ESP32-FOO'
    assert info['target'] == 'unknown'


def test_detect_port_info_no_cache_success() -> None:
    esp = mock.MagicMock()
    chip_cm = mock.MagicMock()
    chip_cm.__enter__.return_value = esp
    fake_info = {'chip_name': 'ESP32-C3', 'target': 'esp32c3', 'mac': '24:6f:28:01:02:03'}

    # Pin version so the context-manager branch is taken regardless of installed esptool.
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_serial.esptool, '__version__', '5.3.0'), \
        mock.patch.object(esp_serial.esptool, 'detect_chip', return_value=chip_cm), \
        mock.patch.object(esp_serial, '_get_esp_port_info', return_value=fake_info):
        result = detect_port_info_no_cache('/dev/ttyUSB0', 'usb-loc', 'desc')
    # fmt: on

    assert isinstance(result, EspPortInfo)
    assert result.support_esptool is True
    assert result.device == '/dev/ttyUSB0'
    assert result.location == 'usb-loc'
    # Note: on the esptool-success path the info dict is replaced wholesale by
    # _get_esp_port_info(), so the passed serial description is not carried over.
    assert result.serial_description == 'desc'
    assert result.target == 'esp32c3'
    esp.hard_reset.assert_called_once()


def test_detect_port_info_no_cache_fatal_error() -> None:
    with mock.patch.object(esp_serial.esptool, 'detect_chip', side_effect=esptool.util.FatalError('boom')):
        result = detect_port_info_no_cache('/dev/ttyUSB1', 'loc2', 'serial-desc')

    assert result.support_esptool is False
    assert result.device == '/dev/ttyUSB1'
    assert result.serial_description == 'serial-desc'
    assert 'boom' in result.chip_description


def test_list_all_esp_ports() -> None:
    port_a = mock.MagicMock(device='/dev/ttyUSB0', location='loc-a', description='desc-a')
    port_b = mock.MagicMock(device='/dev/ttyUSB1', location='loc-b', description='desc-b')
    info_a = EspPortInfo('/dev/ttyUSB0', 'loc-a', True, target='esp32c3')
    info_b = EspPortInfo('/dev/ttyUSB1', 'loc-b', False)

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_serial, 'get_all_serial_ports', return_value=[port_a, port_b]), \
        mock.patch.object(esp_serial, 'detect_one_port', side_effect=[info_a, info_b]):
        result = list_all_esp_ports()
    # fmt: on

    assert result == [info_a, info_b]


def test_get_available_ports_filters_by_target_and_max_num() -> None:
    ports = [mock.MagicMock() for _ in range(3)]
    infos = [
        EspPortInfo('/dev/ttyUSB0', 'a', True, target='esp32c3'),
        EspPortInfo('/dev/ttyUSB1', 'b', True, target='esp32s3'),
        EspPortInfo('/dev/ttyUSB2', 'c', True, target='esp32c3'),
    ]
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_serial, 'get_all_serial_ports', return_value=ports), \
        mock.patch.object(esp_serial, 'detect_one_port', side_effect=infos):
        result = get_available_ports('esp32c3')
    # fmt: on
    assert [p.device for p in result] == ['/dev/ttyUSB0', '/dev/ttyUSB2']

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_serial, 'get_all_serial_ports', return_value=ports), \
        mock.patch.object(esp_serial, 'detect_one_port', side_effect=infos):
        limited = get_available_ports('esp32c3', max_num=1)
    # fmt: on
    assert [p.device for p in limited] == ['/dev/ttyUSB0']


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
