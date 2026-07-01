import subprocess
from unittest.mock import patch

import pytest

from esptest.devices import usb_hub
from esptest.devices.usb_hub import (
    UsbHubControl,
    UsbHubError,
    find_port_line,
    parse_hub_and_port,
    port_has_device,
    should_reset,
)


def _status_output(hub: str, port: str, line: str) -> str:
    return (
        'Current status for hub {} [05e3:0610 GenesysLogic USB2.1 Hub, USB 2.10, 4 ports, ganged]\n  Port {}: {}\n'
    ).format(hub, port, line)


def test_parse_hub_and_port_accepts_dot_format() -> None:
    assert parse_hub_and_port('1-6.1.2') == ('1-6.1', '2')
    assert parse_hub_and_port('  1-3.4  ') == ('1-3', '4')
    assert parse_hub_and_port('2-5.1') == ('2-5', '1')
    assert parse_hub_and_port('1-6.1.2:1.0') == ('1-6.1', '2')


def test_parse_hub_and_port_accepts_dash_format() -> None:
    assert parse_hub_and_port('1-6') == ('1', '6')
    assert parse_hub_and_port('2-5') == ('2', '5')


@pytest.mark.parametrize(
    'data',
    ['not-a-valid-request', 'hub.port', '1.x.2', '1-2.', '1-6.1.2.abc'],
)
def test_parse_hub_and_port_rejects_invalid_format(data: str) -> None:
    with pytest.raises(ValueError, match='invalid hub and port format'):
        parse_hub_and_port(data)


def test_should_reset_when_no_device_or_bare_vid_pid() -> None:
    assert should_reset('  Port 1: 0101 power connect [10c4:ea60]')
    assert should_reset('  Port 1: 0000 off []')
    assert should_reset('  Port 1: 02a0 power 5gbps Rx.Detect')
    assert should_reset('')

    full_line = '  Port 1: 0103 power enable connect [10c4:ea60 Silicon Labs CP2102N USB to UART Bridge Controller]'
    assert not should_reset(full_line)
    assert port_has_device(full_line)


def test_find_port_line_uses_requested_hub_section() -> None:
    output = (
        'Current status for hub 2-5.1 [05e3:0626 GenesysLogic USB3.1 Hub, USB 3.20, 4 ports, ganged]\n'
        '  Port 1: 02a0 power 5gbps Rx.Detect\n'
        'Current status for hub 1-6.1 [05e3:0610 GenesysLogic USB2.1 Hub, USB 2.10, 4 ports, ganged]\n'
        '  Port 1: 0103 power enable connect [10c4:ea60 Silicon Labs CP2102N USB to UART Bridge Controller]\n'
    )
    assert find_port_line(output, '1-6.1', '1') == (
        '  Port 1: 0103 power enable connect [10c4:ea60 Silicon Labs CP2102N USB to UART Bridge Controller]'
    )


def test_find_port_line_raises_when_missing() -> None:
    output = (
        'Current status for hub 1-6.1 [05e3:0610 GenesysLogic USB2.1 Hub, USB 2.10, 4 ports, ganged]\n'
        '  Port 1: 0101 power connect [10c4:ea60]\n'
    )
    with pytest.raises(ValueError):
        find_port_line(output, '1-6.2', '1')
    with pytest.raises(ValueError):
        find_port_line(output, '1-6.1', '2')


def _completed(args, returncode=0, stdout='', stderr=''):  # type: ignore[no-untyped-def]
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_get_port_status_parses_power_and_device() -> None:
    port_line = '0103 power enable connect [054c:0d58 SONY WH-1000XM4]'
    line = '  Port 2: ' + port_line
    result = _completed(['uhubctl'], stdout=_status_output('1-3', '2', port_line))
    with patch('shutil.which', return_value='/usr/bin/uhubctl'):
        ctrl = UsbHubControl()
    with patch.object(usb_hub.subprocess, 'run', return_value=result):
        status = ctrl.get_port_status('1-3', '2')
    assert status.line == line
    assert status.power_on is True
    assert status.has_device is True


def test_get_status_output_raises_on_failure() -> None:
    result = _completed(['uhubctl'], returncode=1, stderr='uhubctl: device not found')
    with patch('shutil.which', return_value='/usr/bin/uhubctl'):
        ctrl = UsbHubControl()
    with patch.object(usb_hub.subprocess, 'run', return_value=result):
        with pytest.raises(UsbHubError, match='device not found'):
            ctrl.get_status_output('1-6.1', '1')


def test_set_power_invalid_action() -> None:
    with patch('shutil.which', return_value='/usr/bin/uhubctl'):
        ctrl = UsbHubControl()
    with pytest.raises(ValueError, match='invalid action'):
        ctrl.set_power('1-6.1', '1', 'reboot')


def test_set_power_runs_uhubctl_with_action() -> None:
    result = _completed(['uhubctl'], stdout='Sent power cycle request\n')
    with patch('shutil.which', return_value='/usr/bin/uhubctl'):
        ctrl = UsbHubControl()
    with patch.object(usb_hub.subprocess, 'run', return_value=result) as mock_run:
        out = ctrl.set_power('1-6.1', '1', 'cycle')
    assert out == 'Sent power cycle request\n'
    assert mock_run.call_args[0][0] == ['uhubctl', '-f', '-l', '1-6.1', '-p', '1', '-a', 'cycle']


def test_smart_reset_skips_when_device_present() -> None:
    line = '0103 power enable connect [10c4:ea60 Silicon Labs CP2102N USB to UART Bridge Controller]'
    status_result = _completed(['uhubctl'], stdout=_status_output('1-6.1', '1', line))
    with patch('shutil.which', return_value='/usr/bin/uhubctl'):
        ctrl = UsbHubControl()
    with patch.object(usb_hub.subprocess, 'run', return_value=status_result) as mock_run:
        assert ctrl.smart_reset('1-6.1', '1') is None
    assert mock_run.call_count == 1  # only the status query, no cycle


def test_smart_reset_cycles_when_no_device() -> None:
    status_result = _completed(['uhubctl'], stdout=_status_output('1-6.1', '1', '0101 power connect [10c4:ea60]'))
    cycle_result = _completed(['uhubctl'], stdout='Sent power cycle request\n')

    def run_side_effect(args, **kwargs):  # type: ignore[no-untyped-def]
        if '-a' in args:
            return cycle_result
        return status_result

    with patch('shutil.which', return_value='/usr/bin/uhubctl'):
        ctrl = UsbHubControl()
    with patch.object(usb_hub.subprocess, 'run', side_effect=run_side_effect) as mock_run:
        out = ctrl.smart_reset('1-6.1', '1')
    assert out == 'Sent power cycle request\n'
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[1][0][0] == ['uhubctl', '-f', '-l', '1-6.1', '-p', '1', '-a', 'cycle']
