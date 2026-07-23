from unittest import mock

import pytest
import serial

import esptest.devices.serial_tools as serial_tools


def _make_port(device: str = '/dev/ttyUSB0', name: str = 'ttyUSB0', location: str = '1-1.1') -> mock.MagicMock:
    port = mock.MagicMock()
    port.device = device
    port.name = name
    port.location = location
    return port


def test_get_serial_port_info_matches_device_name_or_location() -> None:
    ports = [_make_port()]
    with mock.patch.object(serial_tools, 'get_all_serial_ports', return_value=ports):
        assert serial_tools.get_serial_port_info('/dev/ttyUSB0') is ports[0]
        assert serial_tools.get_serial_port_info('ttyUSB0') is ports[0]
        assert serial_tools.get_serial_port_info('1-1.1') is ports[0]


def test_get_serial_port_info_raises_when_missing() -> None:
    with mock.patch.object(serial_tools, 'get_all_serial_ports', return_value=[]):
        with pytest.raises(serial.SerialException, match='Can not find port'):
            serial_tools.get_serial_port_info('/dev/ttyUSB9')


def test_compute_serial_port_reuses_get_serial_port_info() -> None:
    port = _make_port(device='/dev/ttyUSB3')
    with mock.patch.object(serial_tools, 'get_serial_port_info', return_value=port) as get_info:
        assert serial_tools.compute_serial_port('1-1.1') == '/dev/ttyUSB3'
    get_info.assert_called_once_with('1-1.1')


def test_compute_serial_port_strict_raises() -> None:
    with mock.patch.object(
        serial_tools,
        'get_serial_port_info',
        side_effect=serial.SerialException('Can not find port x'),
    ):
        with pytest.raises(serial.SerialException, match='Can not compute'):
            serial_tools.compute_serial_port('missing', strict=True)


def test_compute_serial_port_non_strict_returns_input() -> None:
    with mock.patch.object(
        serial_tools,
        'get_serial_port_info',
        side_effect=serial.SerialException('Can not find port x'),
    ):
        assert serial_tools.compute_serial_port('missing', strict=False) == 'missing'


def test_compute_serial_port_skips_remote_url() -> None:
    with mock.patch.object(serial_tools, 'get_serial_port_info') as get_info:
        assert serial_tools.compute_serial_port('socket://host:1234') == 'socket://host:1234'
    get_info.assert_not_called()
