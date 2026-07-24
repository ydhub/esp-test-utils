from unittest import mock

import esptool
import pytest
import serial
from esptool import FatalError

from esptest.devices import esp_serial
from esptest.devices.esp_serial import (
    EspPortInfo,
    _chip_name_to_target,
    _get_esp_port_info,
    detect_one_port,
    detect_port_info_no_cache,
    esptool_detect_chip,
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
    assert info['chip_rev_full'] == 4  # major*100 + minor
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


def test_esptool_detect_chip_uses_context_manager_on_4_8() -> None:
    chip = mock.MagicMock()
    chip.__enter__.return_value = chip
    chip.__exit__.return_value = None

    # fmt: off
    with mock.patch.object(esp_serial.esptool, '__version__', '4.8.0'), \
        mock.patch.object(esp_serial.esptool, 'detect_chip', return_value=chip) as detect:
        with esptool_detect_chip(
            '/dev/ttyUSB1', baudrate=460800, connect_attempts=3, connect_mode='no-reset'
        ) as esp:
            assert esp is chip
    # fmt: on

    detect.assert_called_once_with('/dev/ttyUSB1', baud=460800, connect_attempts=3, connect_mode='no-reset')
    chip.__enter__.assert_called_once()
    chip.__exit__.assert_called_once()


def test_esptool_detect_chip_closes_port_on_4_7() -> None:
    mock_port = mock.MagicMock()
    mock_esp = mock.MagicMock()
    mock_esp._port = mock_port

    # fmt: off
    with mock.patch.object(esp_serial.esptool, '__version__', '4.7.0'), \
        mock.patch.object(esp_serial.esptool, 'detect_chip', return_value=mock_esp) as detect:
        with esptool_detect_chip('/dev/ttyUSB1', baud=115200, connect_attempts=2) as esp:
            assert esp is mock_esp
    # fmt: on

    detect.assert_called_once_with('/dev/ttyUSB1', baud=115200, connect_attempts=2)
    mock_port.close.assert_called_once()


def test_esptool_detect_chip_closes_port_when_body_raises_on_4_7() -> None:
    mock_port = mock.MagicMock()
    mock_esp = mock.MagicMock()
    mock_esp._port = mock_port

    # fmt: off
    with mock.patch.object(esp_serial.esptool, '__version__', '4.7.0'), \
        mock.patch.object(esp_serial.esptool, 'detect_chip', return_value=mock_esp):
        with pytest.raises(RuntimeError, match='boom'):
            with esptool_detect_chip('/dev/ttyUSB1'):
                raise RuntimeError('boom')
    # fmt: on

    mock_port.close.assert_called_once()


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
    with mock.patch.object(esp_serial.esptool, 'detect_chip', side_effect=FatalError('boom')):
        result = detect_port_info_no_cache('/dev/ttyUSB1', 'loc2', 'serial-desc')

    assert result.support_esptool is False
    assert result.device == '/dev/ttyUSB1'
    assert result.serial_description == 'serial-desc'
    assert 'boom' in result.chip_description


def test_detect_port_info_no_cache_serial_timeout() -> None:
    """SerialTimeoutException must not abort listing; treat as non-esptool port."""
    with mock.patch.object(
        esp_serial.esptool,
        'detect_chip',
        side_effect=serial.SerialTimeoutException('Write timeout'),
    ):
        result = detect_port_info_no_cache('/dev/ttyACM0', '1-10.3.2', 'USB-SPI-BRIDGE')

    assert result.support_esptool is False
    assert result.device == '/dev/ttyACM0'
    assert result.serial_description == 'USB-SPI-BRIDGE'
    assert 'Write timeout' in result.chip_description


def test_detect_port_info_no_cache_closes_port_on_serial_error_old_esptool() -> None:
    """Old esptool path must close the port if SerialException occurs after open."""
    mock_port = mock.MagicMock()
    mock_esp = mock.MagicMock()
    mock_esp._port = mock_port

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_serial.esptool, '__version__', '4.7.0'), \
        mock.patch.object(esp_serial.esptool, 'detect_chip', return_value=mock_esp), \
        mock.patch.object(
            esp_serial,
            '_get_esp_port_info',
            side_effect=serial.SerialTimeoutException('Write timeout'),
        ):
        result = detect_port_info_no_cache('/dev/ttyUSB0', 'loc', 'desc')
    # fmt: on

    mock_port.close.assert_called_once()
    assert result.support_esptool is False
    assert result.device == '/dev/ttyUSB0'
    assert 'Write timeout' in result.chip_description


def test_detect_one_port_skips_usb_spi_bridge() -> None:
    """Espressif USB-SPI-BRIDGE (303a:4001) is not a UART ROM port for esptool."""
    port = mock.MagicMock(
        device='/dev/ttyACM0',
        location='1-10.3.2',
        description='Espressif USB-SPI-BRIDGE',
        vid=0x303A,
        pid=0x4001,
    )
    with mock.patch.object(esp_serial, 'detect_port_info_no_cache') as detect_mock:
        result = detect_one_port(port)

    detect_mock.assert_not_called()
    assert result.support_esptool is False
    assert result.device == '/dev/ttyACM0'
    assert result.serial_description == 'Espressif USB-SPI-BRIDGE'


def test_detect_one_port_respects_empty_skip_list() -> None:
    """Empty SKIP_ESPTOOL_DETECT_VID_PID disables skip; detect still runs."""
    port = mock.MagicMock(
        device='/dev/ttyACM0',
        location='1-10.3.2',
        description='Espressif USB-SPI-BRIDGE',
        vid=0x303A,
        pid=0x4001,
    )
    info = EspPortInfo('/dev/ttyACM0', '1-10.3.2', False, serial_description='Espressif USB-SPI-BRIDGE')
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_serial.g, 'SKIP_ESPTOOL_DETECT_VID_PID', frozenset()), \
        mock.patch.object(esp_serial, 'detect_port_info_no_cache', return_value=info) as detect_mock:
        result = detect_one_port(port)
    # fmt: on

    detect_mock.assert_called_once_with('/dev/ttyACM0', '1-10.3.2', 'Espressif USB-SPI-BRIDGE')
    assert result is info


def test_list_all_esp_ports_continues_after_detect_failure() -> None:
    """SerialTimeoutException on one port must not stop listing the remaining ports."""
    # Non-skip VID:PID so detect_port_info_no_cache actually runs for port_a.
    port_a = mock.MagicMock(device='/dev/ttyACM0', location='loc-a', description='bad', vid=0x1A86, pid=0x7523)
    port_b = mock.MagicMock(device='/dev/ttyUSB0', location='loc-b', description='ok', vid=0x10C4, pid=0xEA60)

    mock_esp = mock.MagicMock()
    mock_esp.__enter__ = mock.Mock(return_value=mock_esp)
    mock_esp.__exit__ = mock.Mock(return_value=None)

    def detect_chip_side_effect(device: str) -> mock.MagicMock:
        if device == '/dev/ttyACM0':
            raise serial.SerialTimeoutException('Write timeout')
        return mock_esp

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_serial, 'get_all_serial_ports', return_value=[port_a, port_b]), \
        mock.patch.object(esp_serial.esptool, 'detect_chip', side_effect=detect_chip_side_effect), \
        mock.patch.object(
            esp_serial,
            '_get_esp_port_info',
            return_value={'target': 'esp32c3', 'chip_name': 'ESP32-C3'},
        ):
        detect_one_port.cache_clear()
        result = list_all_esp_ports()
    # fmt: on

    assert len(result) == 2
    assert result[0].device == '/dev/ttyACM0'
    assert result[0].support_esptool is False
    assert 'Write timeout' in result[0].chip_description
    assert result[1].device == '/dev/ttyUSB0'
    assert result[1].support_esptool is True
    assert result[1].target == 'esp32c3'


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
