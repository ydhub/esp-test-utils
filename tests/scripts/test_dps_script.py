from unittest import mock

import pytest

from esptest.scripts import dps


def test_port_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.object(dps, 'DPS') as dps_class:
        with pytest.raises(SystemExit) as exc:
            dps.main([])

    assert exc.value.code == 2
    assert 'required: -p/--port' in capsys.readouterr().err
    dps_class.assert_not_called()


def test_output_on_requires_explicit_voltage(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.object(dps, 'DPS') as dps_class:
        with pytest.raises(SystemExit) as exc:
            dps.main(['--port', '/dev/ttyUSB0', '--output', 'on'])

    assert exc.value.code == 2
    assert '--output on requires --voltage' in capsys.readouterr().err
    dps_class.assert_not_called()


def test_output_off_does_not_require_voltage() -> None:
    with mock.patch.object(dps, 'print_status'), mock.patch.object(dps, 'DPS') as dps_class:
        device = dps_class.return_value
        device.__enter__.return_value = device
        device.set_output.return_value = False

        assert dps.main(['--port', '/dev/ttyUSB0', '--output', 'off']) == 0

    assert device.method_calls == [
        mock.call.set_output(False),
        mock.call.read_status(),
    ]


def test_output_off_skips_configuration() -> None:
    with mock.patch.object(dps, 'print_status'), mock.patch.object(dps, 'DPS') as dps_class:
        device = dps_class.return_value
        device.__enter__.return_value = device
        device.set_output.return_value = False

        assert dps.main(['--port', '/dev/ttyUSB0', '--voltage', '3.3', '--current', '1.5', '--output', 'off']) == 0

    assert device.method_calls == [
        mock.call.set_output(False),
        mock.call.read_status(),
    ]
