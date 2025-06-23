# pylint: disable=unused-import
import warnings

from ..adapter.port.serial_port import SerialPort as SerialDut  # noqa: F401

warnings.warn(
    'Please use SerialPort instead of SerialDut.',
    category=DeprecationWarning,
)
