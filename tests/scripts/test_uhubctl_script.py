from unittest import mock

import pytest

from esptest.devices.usb_hub import UsbPortStatus
from esptest.devices.usb_topology import UsbSnapshot
from esptest.scripts import uhubctl


def test_main_status_prints_port_state(capsys: pytest.CaptureFixture) -> None:
    status = UsbPortStatus(
        hub='1-6.1',
        port='2',
        line='  Port 2: 0103 power enable connect [10c4:ea60 CP2102]',
    )
    ctrl = mock.Mock()
    ctrl.get_port_status.return_value = status

    # fmt: off
    with mock.patch.object(uhubctl, 'UsbHubControl', return_value=ctrl), mock.patch.object(
        uhubctl.sys, 'argv', ['uhubctl', 'status', '--port', '1-6.1.2']
    ):
    # fmt: on
        uhubctl.main()

    ctrl.get_port_status.assert_called_once_with('1-6.1', '2')
    out = capsys.readouterr().out
    assert 'Port 2:' in out
    assert 'power=True device=True' in out


def test_main_reset_skips_when_device_present(capsys: pytest.CaptureFixture) -> None:
    ctrl = mock.Mock()
    ctrl.smart_reset.return_value = None

    # fmt: off
    with mock.patch.object(uhubctl, 'UsbHubControl', return_value=ctrl), mock.patch.object(
        uhubctl.sys, 'argv', ['uhubctl', 'reset', '--hub', '1-6.1', '--port', '2']
    ):
    # fmt: on
        uhubctl.main()

    ctrl.smart_reset.assert_called_once_with('1-6.1', '2')
    assert 'SKIPPED' in capsys.readouterr().out


def test_main_ls_prints_topology(capsys: pytest.CaptureFixture) -> None:
    snapshot = UsbSnapshot()

    # fmt: off
    with mock.patch.object(uhubctl, 'scan_usb', return_value=snapshot) as scan_usb, mock.patch.object(
        uhubctl, 'format_tree', return_value='usb tree'
    ) as format_tree, mock.patch.object(uhubctl.sys, 'argv', ['uhubctl', 'ls', '--all']):
    # fmt: on
        uhubctl.main()

    scan_usb.assert_called_once_with(uhubctl.DEFAULT_SYSFS)
    format_tree.assert_called_once_with(snapshot, show_empty=True)
    assert capsys.readouterr().out == 'usb tree\n'


def test_main_monitor_dispatches(capsys: pytest.CaptureFixture) -> None:
    # fmt: off
    with mock.patch.object(uhubctl, 'monitor_usb') as monitor_usb, mock.patch.object(
        uhubctl.sys, 'argv', ['uhubctl', 'monitor', '--interval', '0.2']
    ):
    # fmt: on
        uhubctl.main()

    monitor_usb.assert_called_once_with(uhubctl.DEFAULT_SYSFS, interval=0.2)
    assert 'monitoring USB changes' in capsys.readouterr().out


def test_cli_reports_invalid_location(caplog: pytest.LogCaptureFixture) -> None:
    with mock.patch.object(uhubctl.sys, 'argv', ['uhubctl', 'status', '--port', 'invalid']):
        with pytest.raises(SystemExit) as exc_info:
            uhubctl.cli()

    assert exc_info.value.code == 1
    assert 'invalid hub and port format' in caplog.text


def test_cli_reports_usb_hub_error(caplog: pytest.LogCaptureFixture) -> None:
    with mock.patch.object(uhubctl, 'main', side_effect=uhubctl.UsbHubError('uhubctl failed')):
        with pytest.raises(SystemExit) as exc_info:
            uhubctl.cli()

    assert exc_info.value.code == 1
    assert 'uhubctl failed' in caplog.text
