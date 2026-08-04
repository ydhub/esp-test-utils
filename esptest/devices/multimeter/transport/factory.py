"""Draft: open GPIB by address or VISA resource."""

import platform

import esptest.common.compat_typing as t

from .base import GPIBTransport
from .linux import LinuxGpibTransport
from .windows import VisaGpibTransport


def open_gpib(
    address: t.Optional[int] = None,
    resource: t.Optional[str] = None,
) -> GPIBTransport:
    """Draft: open a GPIB instrument (linux-gpib or pyvisa)."""
    system = platform.system()
    if system == 'Windows':
        return VisaGpibTransport(resource=resource, address=address)
    if resource is not None:
        return VisaGpibTransport(resource=resource, address=address)
    return LinuxGpibTransport(address=address)
