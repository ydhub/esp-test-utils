import time
from typing import TYPE_CHECKING, Any, AnyStr, Dict, Optional, Protocol, Type, TypeAlias

import serial
from serial import Serial, SerialBase

from ...common import to_bytes
from ...logger import get_logger
from .base_port import BasePort

if TYPE_CHECKING:
    MixinBase: TypeAlias = 'BasePort'
else:
    MixinBase = object

logger = get_logger('ser_port')


class SerialBaseProtocol(Protocol):
    @property
    def port(self) -> Optional[str]: ...

    @property
    def baudrate(self) -> Optional[int]: ...

    @property
    def timeout(self) -> Optional[float]: ...

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: AnyStr) -> int: ...


class SerMixin(SerialBaseProtocol):
    @property
    def read_timeout(self) -> float:
        # For PortSpawn
        return self.timeout or 0.001  # type: ignore

    def read_bytes(self, timeout: float = 0.001) -> bytes:
        # For PortSpawn
        assert self.timeout
        assert self.timeout >= 0.001
        if timeout > self.timeout:
            time.sleep(timeout - self.timeout)
        return self.read(1024)  # type: ignore

    def write_bytes(self, data: AnyStr) -> int:
        # For PortSpawn
        self.write(to_bytes(data))
        return len(to_bytes(data))

    def __str__(self) -> str:
        """SerialExt<device=xxx,baudrate=xxx,timeout=xxx>"""
        return f'SerialExt<device={self.port},baudrate={self.baudrate},timeout={self.timeout}>'


class SerialExt(Serial, SerMixin):
    """Add RawPort methods to serial.Serial"""


def serial_add_mixin(cls: Type[Any]) -> Type[Any]:
    """动态为类添加 SerMixin"""
    # 创建一个新的类，继承自原始类和 SerMixin
    # 基类顺序与 SerialExt(Serial, SerMixin) 保持一致
    return type(f'{cls.__name__}Ext', (cls, SerMixin), {})


class SerialPortMixin(MixinBase):
    """Add RawPort methods to serial.Serial"""

    @staticmethod
    def _add_mixin_by_type(raw_port: Any) -> None:
        """根据原始类型添加对应的 mixin"""
        if raw_port is None:
            return
        original_type = type(raw_port)
        # If the original type already includes SerMixin, do nothing.
        # This prevents repeatedly nesting mixin classes when the serial
        # object is reassigned and _add_mixin_by_type is called multiple times.
        if issubclass(original_type, SerMixin):
            return
        if issubclass(original_type, Serial):
            raw_port.__class__ = SerialExt
        elif issubclass(original_type, SerialBase):
            raw_port.__class__ = serial_add_mixin(original_type)

    def __init__(self, raw_port: Any, name: str, log_file: str = '') -> None:
        self._add_mixin_by_type(raw_port)
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
            self._add_mixin_by_type(serial_instance)
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
