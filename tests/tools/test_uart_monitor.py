import asyncio
from unittest import mock

import pytest

from esptest.devices.esp_serial import EspPortInfo
from esptest.tools import uart_monitor
from esptest.tools.uart_monitor import Chip, Device, _update_chip_from_port_info


def _make_device() -> Device:
    return Device(
        name='ttyUSB0',
        sys_device='/dev/ttyUSB0',
        location='loc-a',
        description='desc',
        connected=True,
        last_seen=0.0,
        first_seen=0.0,
        chip=Chip(target='Detecting...'),
    )


def test_update_chip_from_supported_port() -> None:
    chip = Chip()
    esp_port = EspPortInfo(
        '/dev/ttyUSB0',
        'loc-a',
        True,
        chip_description='ESP32-C3 (revision v0.4)',
        mac='24:6f:28:01:02:03',
        chip_version='v0.4',
        chip_xtal='40',
        flash_size='4MB',
        target='esp32c3',
    )
    _update_chip_from_port_info(chip, esp_port)
    assert chip.target == 'esp32c3'
    assert chip.revision == 'v0.4'
    assert chip.xtal == '40MHz'
    assert chip.mac == '24:6f:28:01:02:03'
    assert chip.flash == '4MB'
    assert chip.description == 'ESP32-C3 (revision v0.4)'


def test_update_chip_from_unsupported_port() -> None:
    chip = Chip(target='Detecting...', mac='stale', revision='stale')
    esp_port = EspPortInfo('/dev/ttyUSB1', 'loc-b', False, serial_description='CP2102 USB to UART')
    _update_chip_from_port_info(chip, esp_port)
    assert chip.target == 'unknown'
    assert chip.description == 'CP2102 USB to UART'
    # stale chip details must be cleared
    assert chip.mac == ''
    assert chip.revision == ''


def test_update_chip_empty_xtal_not_suffixed() -> None:
    chip = Chip()
    esp_port = EspPortInfo('/dev/ttyUSB0', 'loc-a', True, chip_xtal='', target='esp32c3')
    _update_chip_from_port_info(chip, esp_port)
    assert chip.xtal == ''


def test_debug_print_respects_debug_flag() -> None:
    uart_monitor.debug_logs.clear()
    with mock.patch.object(uart_monitor, 'DEBUG', False):
        uart_monitor.debug_print('hidden message')
    assert len(uart_monitor.debug_logs) == 0

    with mock.patch.object(uart_monitor, 'DEBUG', True):
        uart_monitor.debug_print('visible', 'message')
    assert len(uart_monitor.debug_logs) == 1
    assert 'visible message' in uart_monitor.debug_logs[-1]
    uart_monitor.debug_logs.clear()


def test_refresh_serial_ports_adds_new_device() -> None:
    fake_port = mock.MagicMock()
    fake_port.usb_interface_path = '/sys/devices/usb/ttyUSB0'
    fake_port.location = '1-1:1.0'
    fake_port.name = 'ttyUSB0'
    fake_port.device = '/dev/ttyUSB0'
    fake_port.description = 'CP2102 USB to UART'

    uart_monitor.devices.clear()
    uart_monitor.recent_devices = []
    while not uart_monitor.detect_queue.empty():
        uart_monitor.detect_queue.get()

    with mock.patch.object(uart_monitor.list_ports, 'comports', return_value=[fake_port]):
        changed = uart_monitor.refresh_serial_ports(initial=True)

    assert changed is True
    assert fake_port.usb_interface_path in uart_monitor.devices
    device = uart_monitor.devices[fake_port.usb_interface_path]
    assert device.sys_device == '/dev/ttyUSB0'
    assert device.location == '1-1:1.0'
    assert device.chip.target == 'Detecting...'
    # newly discovered device must be queued for detection
    assert not uart_monitor.detect_queue.empty()

    uart_monitor.devices.clear()
    while not uart_monitor.detect_queue.empty():
        uart_monitor.detect_queue.get()


def test_detect_port_chip_updates_chip_on_success() -> None:
    device = _make_device()
    esp_port = EspPortInfo('/dev/ttyUSB0', 'loc-a', True, chip_version='v0.4', mac='aa:bb', target='esp32c3')
    with mock.patch.object(uart_monitor, 'detect_port_info_no_cache', return_value=esp_port) as detect_mock:
        asyncio.run(uart_monitor.detect_port_chip(device))

    # success on the first attempt: detect must be called exactly once (no retry)
    detect_mock.assert_called_once()
    assert device.chip.target == 'esp32c3'
    assert device.chip.mac == 'aa:bb'


def test_detect_port_chip_retries_on_failure() -> None:
    device = _make_device()
    failed = EspPortInfo('/dev/ttyUSB0', 'loc-a', False, serial_description='not esp')

    async def _no_sleep(*_args: object, **_kwargs: object) -> None:
        # 3.7-compatible replacement for an async sleep (mock.AsyncMock needs 3.8+)
        return None

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(uart_monitor, 'detect_port_info_no_cache', return_value=failed) as detect_mock, \
        mock.patch.object(uart_monitor.asyncio, 'sleep', new=_no_sleep):
        asyncio.run(uart_monitor.detect_port_chip(device))
    # fmt: on

    # one initial attempt + MAX_DETECT_RETRY retries
    assert detect_mock.call_count == uart_monitor.MAX_DETECT_RETRY + 1
    assert device.chip.target == 'unknown'


def test_detect_chip_skips_lsof_when_missing() -> None:
    """When lsof is unavailable, detection must still run (Windows / minimal hosts)."""
    device = _make_device()
    esp_port = EspPortInfo('/dev/ttyUSB0', 'loc-a', True, target='esp32c3', mac='aa:bb')

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(
        uart_monitor.asyncio, 'create_subprocess_exec', side_effect=FileNotFoundError('lsof')
    ), \
        mock.patch.object(uart_monitor, 'detect_port_info_no_cache', return_value=esp_port) as detect_mock:
        asyncio.run(uart_monitor.detect_chip(device))
    # fmt: on

    detect_mock.assert_called_once()
    assert device.chip.target == 'esp32c3'


def test_refresh_serial_ports_windows_without_usb_interface_path() -> None:
    fake_port = mock.MagicMock()
    fake_port.usb_interface_path = None
    fake_port.hwid = 'USB VID:PID=10C4:EA60'
    fake_port.location = None
    fake_port.name = 'COM3'
    fake_port.device = 'COM3'
    fake_port.description = 'Silicon Labs CP210x'

    uart_monitor.devices.clear()
    uart_monitor.recent_devices = []
    while not uart_monitor.detect_queue.empty():
        uart_monitor.detect_queue.get()

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(uart_monitor.sys, 'platform', 'win32'), \
        mock.patch.object(uart_monitor.list_ports, 'comports', return_value=[fake_port]):
        changed = uart_monitor.refresh_serial_ports(initial=True)
    # fmt: on

    assert changed is True
    assert fake_port.hwid in uart_monitor.devices
    device = uart_monitor.devices[fake_port.hwid]
    assert device.sys_device == 'COM3'
    assert device.location == 'COM3'

    uart_monitor.devices.clear()
    while not uart_monitor.detect_queue.empty():
        uart_monitor.detect_queue.get()


def test_start_monitoring_win_polls_without_pyudev() -> None:
    from esptest.tools import uart_monitor_win

    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(uart_monitor, '_bootstrap_monitoring') as bootstrap, \
        mock.patch.object(uart_monitor, 'check_new_devices_status', side_effect=[None, KeyboardInterrupt()]), \
        mock.patch.object(uart_monitor_win.time, 'sleep'):
        uart_monitor_win.start_monitoring()
    # fmt: on

    bootstrap.assert_called_once()


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
