import time
from typing import Any
from typing import AnyStr
from typing import Dict
from typing import Optional
from typing import TYPE_CHECKING
from typing import TypeAlias

import serial
from serial import Serial

from ...basic import to_bytes
from ...logger import get_logger


if TYPE_CHECKING:
    from .dut_base import DutPort

    MixinBase: TypeAlias = 'DutPort'
else:
    MixinBase = object

logger = get_logger('dut')


class SerialPort(Serial):
    """Add RawPort methods to serial.Serial"""

    @property
    def read_timeout(self) -> float:
        # For PortSpawn
        return super().timeout  # type: ignore

    def read_bytes(self, timeout: float = 0.001) -> bytes:
        # For PortSpawn
        assert self.timeout
        assert self.timeout >= 0.001
        if timeout > self.timeout:
            time.sleep(timeout - self.timeout)
        return super().read(1024)  # type: ignore

    def write_bytes(self, data: AnyStr) -> None:
        # For PortSpawn
        super().write(to_bytes(data))


class SerialDutMixin(MixinBase):
    """Add RawPort methods to serial.Serial"""

    def __init__(self, dut: Any, name: str, log_file: str = '') -> None:
        if isinstance(dut, Serial):
            dut.__class__ = SerialPort
        super().__init__(dut, name, log_file)
        self._serial_config: Dict[str, Any] = {}

    @property
    def port(self) -> Optional[SerialPort]:  # type: ignore
        return self._port  # type: ignore

    def start_pexpect_proc(self) -> None:
        if not self.port:
            return
        assert self.port.timeout is not None, 'Serial port timeout must be specified!'
        self._serial_config = {
            'port': self.port.port,
            'baudrate': self.port.baudrate,
            'bytesize': self.port.bytesize,
            'parity': self.port.parity,
            'stopbits': self.port.stopbits,
            'timeout': self.port.timeout,
            'xonxoff': self.port.xonxoff,
            'rtscts': self.port.rtscts,
            'write_timeout': self.port.write_timeout,
            'dsrdtr': self.port.dsrdtr,
        }
        if not self.port.is_open:
            self.port.open()
        super().start_pexpect_proc()

    @property
    def serial(self) -> Optional[SerialPort]:
        """Get Current serial instance."""
        return self._port  # type: ignore

    @serial.setter
    def serial(self, serial_instance: Optional[Serial]) -> None:
        """Set serial instance, will close and clean up the old serial resources"""
        if self._port:
            # Close pexpect proc
            self.close()
            # Do not close serial port because the port may not open by this object.
            # if self._port.is_open:
            #     self._port.close()
        if serial_instance:
            self._port = serial_instance
            self._port.__class__ = SerialPort
            self.start_pexpect_proc()

    def close(self) -> None:
        """Close serial port and clean up resources."""
        super().close()
        if self._port:
            self._port = None

    def reopen(self) -> None:
        """Open the same serial port again and enable serial read thread."""
        self.serial = serial.Serial(**self._serial_config)
