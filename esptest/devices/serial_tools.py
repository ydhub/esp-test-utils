from functools import lru_cache
from typing import List

import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo

from ..logger import get_logger

logger = get_logger('devices')


@lru_cache()
def get_all_serial_ports(user: str = 'default', include_links: bool = False) -> List[ListPortInfo]:
    """list_ports could spend a very long time if there are many ports"""
    # pylint: disable=unused-argument
    # disable unused argument user was only used by lru_cache
    # remove /dev/ttyS0  {location: None, pid: None, hwid: PNP0501, subsystem:pnp, serial_number: None}
    return [p for p in serial.tools.list_ports.comports(include_links=include_links) if p.device and p.location]


def compute_serial_port(port: str, strict: bool = False) -> str:
    """Get the real serial port device from device, port name or usb location

    Args:
        port (str): device, port name or usb location
        strict (bool, optional): raise Exception if not found locally.

    Returns:
        str: port device. return the given input port
    """
    ports = get_all_serial_ports(include_links=True)
    for p in ports:
        if port in [p.name, p.device, p.location]:
            assert isinstance(p.device, str)
            return p.device
    if strict:
        raise serial.SerialException(f'Can not compute {port}')
    logger.warning(f'Can not compute port {port}, is it exist?')
    return port
