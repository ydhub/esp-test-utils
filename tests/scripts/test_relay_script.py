from unittest import mock

import pytest

from esptest.scripts import relay


def test_relay_open_writes_open_command() -> None:
    serial_instance = mock.MagicMock()
    serial_ctx = mock.MagicMock()
    serial_ctx.__enter__.return_value = serial_instance

    # Keep Python 3.7-compatible multi-context with-statement formatting.
    # fmt: off
    with mock.patch.object(relay, 'get_relay_device', return_value='/dev/ttyUSB0'), \
        mock.patch.object(relay.serial, 'Serial', return_value=serial_ctx) as serial_ctor, \
        mock.patch.object(relay.time, 'sleep'):
        controller = relay.RelayControl('ttyUSB0')
        controller.open()
    # fmt: on

    serial_ctor.assert_called_once_with('/dev/ttyUSB0', baudrate=9600, timeout=0.01)
    serial_instance.write.assert_called_once_with(bytes.fromhex(relay.CHANNEL1_OPEN_HEX))


def test_relay_close_writes_close_command() -> None:
    serial_instance = mock.MagicMock()
    serial_ctx = mock.MagicMock()
    serial_ctx.__enter__.return_value = serial_instance

    # fmt: off
    with mock.patch.object(relay, 'get_relay_device', return_value='/dev/ttyUSB0'), \
        mock.patch.object(relay.serial, 'Serial', return_value=serial_ctx) as serial_ctor, \
        mock.patch.object(relay.time, 'sleep'):
        controller = relay.RelayControl('ttyUSB0')
        controller.close()
    # fmt: on

    serial_ctor.assert_called_once_with('/dev/ttyUSB0', baudrate=9600, timeout=0.01)
    serial_instance.write.assert_called_once_with(bytes.fromhex(relay.CHANNEL1_CLOSE_HEX))


def test_check_phone_exits_when_battery_level_unavailable() -> None:
    # fmt: off
    with mock.patch.object(relay, 'get_relay_device', return_value='/dev/ttyUSB0'), \
        mock.patch.object(relay.RelayControl, 'open') as open_mock, \
        mock.patch.object(relay, 'get_battery_level_pct', return_value=None), \
        mock.patch.object(relay.time, 'sleep'):
        controller = relay.RelayControl('ttyUSB0')
        with pytest.raises(SystemExit) as exc:
            controller.check_phone()
    # fmt: on

    assert exc.value.code == 1
    open_mock.assert_called_once()


def test_check_phone_closes_when_battery_level_is_high() -> None:
    # fmt: off
    with mock.patch.object(relay, 'get_relay_device', return_value='/dev/ttyUSB0'), \
        mock.patch.object(relay.RelayControl, 'open') as open_mock, \
        mock.patch.object(relay, 'get_battery_level_pct', return_value=80), \
        mock.patch.object(relay.RelayControl, 'close') as close_mock, \
        mock.patch.object(relay.time, 'sleep'), \
        mock.patch.object(relay.logging, 'info'):
        controller = relay.RelayControl('ttyUSB0')
        controller.check_phone()
    # fmt: on

    open_mock.assert_called_once()
    close_mock.assert_called_once()


def test_check_phone_keeps_relay_open_when_battery_level_is_low() -> None:
    # fmt: off
    with mock.patch.object(relay, 'get_relay_device', return_value='/dev/ttyUSB0'), \
        mock.patch.object(relay.RelayControl, 'open') as open_mock, \
        mock.patch.object(relay, 'get_battery_level_pct', return_value=79), \
        mock.patch.object(relay.RelayControl, 'close') as close_mock, \
        mock.patch.object(relay.time, 'sleep'), \
        mock.patch.object(relay.logging, 'info'):
        controller = relay.RelayControl('ttyUSB0')
        controller.check_phone()
    # fmt: on

    open_mock.assert_called_once()
    close_mock.assert_not_called()
