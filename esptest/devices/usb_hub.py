"""Control USB hub port power via the ``uhubctl`` command line tool.

This wraps `uhubctl <https://github.com/mvp/uhubctl>`_ to switch USB hub
ports on/off/cycle and to power-cycle a port only when nothing is enumerated
on it (useful to recover devices that failed to come up after a flash/reset).

The USB location string understood by :func:`parse_hub_and_port` matches the
sysfs path used elsewhere in this package (e.g. ``1-6.1.2``), so it can be fed
directly from a serial port ``location``.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger('devices')

UHUBCTL_TIMEOUT_SECONDS = 15

# uhubctl power actions, see `uhubctl --help` (-a/--action)
HUB_ACTIONS = ('off', 'on', 'cycle', 'toggle')

# A populated uhubctl status line ends with a device entry like
# "[10c4:ea60 Silicon Labs CP2102N USB to UART Bridge Controller]".
# An empty/bare entry such as "[]" or "[10c4:ea60]" (no description) means no
# device is properly enumerated on the port.
_DEVICE_PRESENT_RE = re.compile(r'.*\[\s*[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\s+.+\].*')


class UsbHubError(OSError):
    """Raised when a uhubctl command fails."""


def parse_hub_and_port(data: str) -> t.Tuple[str, str]:
    """Split a USB location string into ``(hub, port)`` understood by uhubctl.

    Examples:
        ``1-6.1.2``     -> ``('1-6.1', '2')``
        ``1-6.1.2:1.0`` -> ``('1-6.1', '2')`` (``:1.0`` interface suffix dropped)
        ``1-6``         -> ``('1', '6')``
    """
    data = data.strip()
    data = data.split(':')[0]  # drop the ":1.0" interface suffix (e.g. ttyACM)
    if '.' in data:
        # eg: "1-6.1.2"
        if not re.match(r'^\d+-[\d.]+\.\d+$', data):
            raise ValueError(f'invalid hub and port format: {data}')
        hub, port = data.rsplit('.', 1)
        return hub, port
    if re.match(r'^\d+-\d+$', data):
        # eg: "1-6"
        hub, port = data.split('-', 1)
        return hub, port
    raise ValueError(f'invalid hub and port format: {data}')


def port_has_device(line: str) -> bool:
    """Return True if a uhubctl status line shows an enumerated device."""
    return bool(_DEVICE_PRESENT_RE.fullmatch(line))


def should_reset(line: str) -> bool:
    """Return True if the port has no enumerated device and should be reset."""
    return not port_has_device(line)


def find_port_line(output: str, hub: str, port: str) -> str:
    """Return the ``Port <port>:`` status line that belongs to ``hub``.

    uhubctl may list several hubs (e.g. the USB2 and USB3 companion) so we only
    look at lines under the requested ``Current status for hub <hub>`` header.
    """
    in_requested_hub = False
    for line in output.splitlines():
        if line.startswith('Current status for hub '):
            in_requested_hub = line.startswith(f'Current status for hub {hub} ')
            continue
        if in_requested_hub and f'Port {port}:' in line:
            return line
    raise ValueError(f'port {port} not found for hub {hub}')


@dataclass
class UsbPortStatus:
    hub: str
    port: str
    line: str  # the raw uhubctl status line for this port

    @property
    def has_device(self) -> bool:
        return port_has_device(self.line)

    @property
    def power_on(self) -> bool:
        # flags live between "Port N:" and the optional "[...]" device part
        flags = self.line.split('[', 1)[0]
        return 'power' in flags.split()


class UsbHubControl:
    def __init__(self, timeout: float = UHUBCTL_TIMEOUT_SECONDS, sudo: bool = False) -> None:
        self.timeout = timeout
        self.sudo = sudo
        if not shutil.which('uhubctl'):
            logger.warning('uhubctl not found in PATH, install it from https://github.com/mvp/uhubctl')

    def _run(self, args: t.List[str]) -> 'subprocess.CompletedProcess[str]':
        cmd = ['uhubctl'] + args
        if self.sudo:
            cmd = ['sudo'] + cmd
        logger.debug(f'running: {" ".join(cmd)}')
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )

    def get_status_output(self, hub: str, port: str) -> str:
        """Return the raw uhubctl ``-f -l <hub> -p <port>`` status output."""
        result = self._run(['-f', '-l', hub, '-p', port])
        if result.returncode != 0:
            raise UsbHubError((result.stderr or result.stdout).strip() or 'uhubctl status failed')
        return result.stdout

    def get_port_status(self, hub: str, port: str) -> UsbPortStatus:
        output = self.get_status_output(hub, port)
        line = find_port_line(output, hub, port)
        return UsbPortStatus(hub=hub, port=port, line=line)

    def set_power(self, hub: str, port: str, action: str) -> str:
        """Run ``uhubctl -a <action>`` on the port and return its stdout."""
        if action not in HUB_ACTIONS:
            raise ValueError(f'invalid action: {action}, must be one of {HUB_ACTIONS}')
        result = self._run(['-f', '-l', hub, '-p', port, '-a', action])
        if result.returncode != 0:
            raise UsbHubError((result.stderr or result.stdout).strip() or f'uhubctl {action} failed')
        return result.stdout

    def smart_reset(self, hub: str, port: str) -> t.Optional[str]:
        """Power-cycle the port only when no device is currently enumerated.

        Returns the uhubctl cycle output, or ``None`` if the reset was skipped
        because a device is already present on the port.
        """
        status = self.get_port_status(hub, port)
        if not should_reset(status.line):
            logger.info(f'skip reset, device already present on {hub}.{port}: {status.line.strip()}')
            return None
        logger.info(f'resetting {hub}.{port} (no device detected)')
        return self.set_power(hub, port, 'cycle')
