"""Draft: Multimeter API (GPIB first; API may change).

Initialized from ATS AutoTestScript GPIB code at
e10787397ad19426fd17d9b64d97f47f768da349.
"""

from . import gpib as _gpib  # noqa: F401  # register backend
from .base import DeviceInfo, MultimeterError
from .facade import Multimeter
from .factory import get_multimeter_specific, list_multimeters

DRAFT = True

__all__ = [
    'DRAFT',
    'DeviceInfo',
    'Multimeter',
    'MultimeterError',
    'get_multimeter_specific',
    'list_multimeters',
]
