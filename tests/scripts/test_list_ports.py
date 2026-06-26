import json
from unittest import mock

import pytest

from esptest.devices.esp_serial import EspPortInfo
from esptest.scripts import list_ports


def _sample_ports() -> list:
    return [
        EspPortInfo(
            '/dev/ttyUSB0',
            'loc-a',
            True,
            chip_name='ESP32-C3',
            chip_description='ESP32-C3 (revision v0.4)',
            mac='24:6f:28:01:02:03',
            chip_version='v0.4',
            target='esp32c3',
        ),
        EspPortInfo('/dev/ttyUSB1', 'loc-b', False, serial_description='CP2102 USB to UART'),
    ]


def test_main_json_format(capsys: pytest.CaptureFixture) -> None:
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(list_ports, 'list_all_esp_ports', return_value=_sample_ports()), \
        mock.patch.object(list_ports.sys, 'argv', ['list_ports', '--format', 'json']):
        list_ports.main()
    # fmt: on

    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]['device'] == '/dev/ttyUSB0'
    assert data[0]['target'] == 'esp32c3'
    assert data[1]['support_esptool'] is False


def test_main_text_format(capsys: pytest.CaptureFixture) -> None:
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(list_ports, 'list_all_esp_ports', return_value=_sample_ports()), \
        mock.patch.object(list_ports.sys, 'argv', ['list_ports']):
        list_ports.main()
    # fmt: on

    out = capsys.readouterr().out
    assert 'All devices:' in out
    assert '/dev/ttyUSB0' in out
    assert 'esp32c3' in out
    # esptool-unsupported ports show a fallback marker
    assert 'not esp port' in out


def test_main_monitor_dispatches(capsys: pytest.CaptureFixture) -> None:
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(list_ports, 'run_uart_monitor') as run_monitor, \
        mock.patch.object(list_ports, 'list_all_esp_ports') as list_ports_mock, \
        mock.patch.object(list_ports.sys, 'argv', ['list_ports', '--monitor']):
        list_ports.main()
    # fmt: on

    run_monitor.assert_called_once()
    list_ports_mock.assert_not_called()


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
