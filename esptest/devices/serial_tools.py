import logging
import shutil
import subprocess
from functools import lru_cache

import serial
import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger('devices')


@lru_cache()
def get_all_serial_ports(user: str = 'default', include_links: bool = False) -> t.List[ListPortInfo]:
    """list_ports could spend a very long time if there are many ports"""
    # pylint: disable=unused-argument
    # disable unused argument user was only used by lru_cache
    # remove /dev/ttyS0  {location: None, pid: None, hwid: PNP0501, subsystem:pnp, serial_number: None}
    return [p for p in serial.tools.list_ports.comports(include_links=include_links) if p.device and p.location]


def get_serial_port_info(port: str) -> ListPortInfo:
    """Get the serial port info from device, port name or usb location."""
    ports = get_all_serial_ports(include_links=True)
    for p in ports:
        if port in [p.name, p.device, p.location]:
            assert isinstance(p.device, str)
            return p
    raise serial.SerialException(f'Can not find port {port}')


def compute_serial_port(port: str, strict: bool = False) -> str:
    """Get the real serial port device from device, port name or usb location

    Args:
        port (str): device, port name or usb location
        strict (bool, optional): raise Exception if not found locally.

    Returns:
        str: port device. return the given input port
    """
    if '://' in port:
        logging.debug(f'Skip compute remote port {port}')
        return port
    try:
        info = get_serial_port_info(port)
        return str(info.device)
    except serial.SerialException as exc:
        if strict:
            raise serial.SerialException(f'Can not compute {port}') from exc
        logger.warning(f'Can not compute port {port}, is it exist?')
        return port


def is_serial_port_in_use(port: str) -> bool:
    """Return whether the serial device is likely open in another process.

    Resolves ``port`` with :func:`compute_serial_port`, then prefers ``fuser(1)``
    (``fuser -s`` on the device path: exit 0 means some process is using the
    file). If ``fuser`` is unavailable, fails, or returns an unexpected exit
    code, falls back to ``lsof(8)`` (exit 0 means holders were found).

    If neither tool is available or both fail, raise OSError (occupancy unknown; callers may still open the port).
    """
    device = compute_serial_port(port)

    check_commands = {
        'fuser': {
            'cmd': ['fuser', '-s', device],
            'return_code': 0,
        },
        'lsof': {
            'cmd': ['lsof', device],
            'return_code': 0,
        },
    }

    for cmd, cmd_info in check_commands.items():
        if shutil.which(cmd):
            try:
                _cmd: t.List[str] = cmd_info['cmd']  # type: ignore
                proc = subprocess.run(
                    _cmd,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as e:
                raise OSError(f'Failed to run {cmd} on {device}') from e
            if proc.returncode == cmd_info['return_code']:
                return True
            return False
    raise OSError(f'Failed to check if serial port {device} is in use')
