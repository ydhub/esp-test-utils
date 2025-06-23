import os
import time

import esptool
import serial

import esptest.common.compat_typing as t

from ...common.encoding import to_bytes
from ...devices.serial_tools import compute_serial_port, get_all_serial_ports

if t.TYPE_CHECKING:
    # Do not import DutBase
    from ..port.base_port import BasePort
    from .dut_base import DutConfig

    class BaseProtocol(BasePort):
        @property
        def dut_config(self) -> DutConfig: ...
else:
    BaseProtocol = object


class EspSerial:
    """Add RawPort methods to esp serial"""

    def __init__(self, esp: esptool.ESPLoader) -> None:
        self._esp = esp
        self._serial: serial.Serial = esp._port

    @property
    def read_timeout(self) -> float:
        # For PortSpawn
        return self._serial.timeout  # type: ignore

    def read_bytes(self, timeout: float = 0.001) -> bytes:
        # For PortSpawn
        assert self._serial.timeout
        assert self._serial.timeout >= 0.001
        if timeout > self._serial.timeout:
            time.sleep(timeout - self._serial.timeout)
        return self._serial.read(1024)  # type: ignore

    def write_bytes(self, data: t.AnyStr) -> None:
        # For PortSpawn
        self._serial.write(to_bytes(data))


class EspMixin(BaseProtocol):
    def hard_reset(self) -> None:
        self.esp.hard_reset()

    def _esptool_open_port(self, port: str, **kwargs: t.Any) -> esptool.ESPLoader:
        ports = get_all_serial_ports()
        port = compute_serial_port(port) if port else ''
        esp = esptool.get_default_connected_device(
            ports,
            port,
            connect_attempts=3,
            initial_baud=os.getenv('ESPBAUD') or 921600,
            chip=kwargs.get('chip', 'auto'),
        )
        return esp

    def _esptool_path(self, use_esptool: str = '') -> str:
        if use_esptool:
            return use_esptool
        return 'esptool.py'

    # def run_esptool(self, args, use_esptool: str = ''):
    #     """Run esptool method with given args"""
    #     _esptool = self._esptool_path(use_esptool)
    #     with self.disable_redirect_thread():
    #         esptool.main(args, esp=self._esp)
    #         # Need to reset esp after running esptool
    #         self._esp.hard_reset()

    @property
    def esp(self) -> esptool.ESPLoader:
        if isinstance(self._raw_port, EspSerial):
            return self._raw_port
        return None
