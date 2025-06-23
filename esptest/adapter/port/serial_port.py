import time
from typing import TYPE_CHECKING, Any, AnyStr, Dict, Optional, TypeAlias

import serial
from serial import Serial

from ...common import to_bytes
from ...logger import get_logger
from .base_port import BasePort

if TYPE_CHECKING:
    MixinBase: TypeAlias = 'BasePort'
else:
    MixinBase = object

logger = get_logger('ser_port')


class SerialExt(Serial):
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


class SerialPortMixin(MixinBase):
    """Add RawPort methods to serial.Serial"""

    def __init__(self, raw_port: Any, name: str, log_file: str = '') -> None:
        if isinstance(raw_port, Serial):
            raw_port.__class__ = SerialExt
        super().__init__(raw_port, name, log_file)
        self._serial_config: Dict[str, Any] = {}

    def start_redirect_thread(self) -> None:
        if not self.serial:
            return
        assert self.serial.timeout is not None, 'Serial port timeout must be specified!'
        self._serial_config = self.serial.get_settings()
        # {
        #     'port': self.serial.port,
        #     'baudrate': self.serial.baudrate,
        #     'bytesize': self.serial.bytesize,
        #     'parity': self.serial.parity,
        #     'stopbits': self.serial.stopbits,
        #     'timeout': self.serial.timeout,
        #     'xonxoff': self.serial.xonxoff,
        #     'rtscts': self.serial.rtscts,
        #     'write_timeout': self.serial.write_timeout,
        #     'dsrdtr': self.serial.dsrdtr,
        # }
        if not self.serial.is_open:
            self.serial.open()
        super().start_redirect_thread()

    @property
    def serial(self) -> Optional[SerialExt]:
        """Get Current serial instance."""
        return self._raw_port  # type: ignore

    @serial.setter
    def serial(self, serial_instance: Optional[Serial]) -> None:
        """Set serial instance, will close and clean up the old serial resources"""
        if self._raw_port:
            # Close pexpect proc
            self.close()
            # Do not close serial port because the port may not open by this object.
            # if self._port.is_open:
            #     self._port.close()
        if serial_instance:
            self._raw_port = serial_instance
            self._raw_port.__class__ = SerialExt
            self.start_redirect_thread()

    def close(self) -> None:
        """Close serial port and clean up resources."""
        super().close()
        if self._raw_port:
            self._raw_port = None

    def reopen(self) -> None:
        """Open the same serial port again and enable serial read thread."""
        self.serial = serial.Serial(**self._serial_config)


class SerialPort(SerialPortMixin, BasePort):
    """A Simple Port class that supports serial read, write, expect

    This class using serial with pexpect.
    """

    def __init__(self, dut: Serial, name: str, log_file: str = '', **kwargs: Any) -> None:
        if not dut:
            self.INIT_START_REDIRECT_THREAD = False  # pylint: disable=invalid-name
        super().__init__(dut, name, log_file, **kwargs)
