"""Draft: GPIB transport (linux-gpib / pyvisa)."""

from .base import GPIBTransport
from .factory import open_gpib

__all__ = ['GPIBTransport', 'open_gpib']
