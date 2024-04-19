from functools import lru_cache
from typing import List

import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo


@lru_cache()
def get_all_serial_ports(user: str = 'default', include_links: bool = False) -> List[ListPortInfo]:
    """list_ports could spend a very long time if there are many ports"""
    # pylint: disable=unused-argument
    # disable unused argument user was only used by lru_cache
    # remove /dev/ttyS0  {location: None, pid: None, hwid: PNP0501, subsystem:pnp, serial_number: None}
    return [p for p in serial.tools.list_ports.comports(include_links=include_links) if p.device and p.location]
