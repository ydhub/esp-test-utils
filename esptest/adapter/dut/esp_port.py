# import os
# import time

# import serial

# import esptest.common.compat_typing as t

# from ...common import to_bytes
# from ...logger import get_logger
# from ..port.base_port import BasePort
# from ...devices.serial_tools import compute_serial_port, get_all_serial_ports

# import esptool

# if t.TYPE_CHECKING:
#     MixinBase: t.TypeAlias = 'BasePort'
# else:
#     MixinBase = object

# logger = get_logger('esp_port')


# class EspSerial:
#     """Add RawPort methods to esp serial"""
#     def __init__(self, esp: esptool.ESPLoader) -> None:
#         self._esp = esp
#         self._serial: serial.Serial = esp._port

#     @property
#     def read_timeout(self) -> float:
#         # For PortSpawn
#         return self._serial.timeout  # type: ignore

#     def read_bytes(self, timeout: float = 0.001) -> bytes:
#         # For PortSpawn
#         assert self.timeout
#         assert self.timeout >= 0.001
#         if timeout > self.timeout:
#             time.sleep(timeout - self.timeout)
#         return self._serial.read(1024)  # type: ignore

#     def write_bytes(self, data: t.AnyStr) -> None:
#         # For PortSpawn
#         self._serial.write(to_bytes(data))


# class EspPort(BasePort):
#     """esp targets using esptool connections."""

#     def __init__(self, dut: t.Union[str, esptool.ESPLoader], name: str, log_file: str = '', **kwargs: t.Any) -> None:
#         self._stop_esptool_when_close = True
#         if isinstance(dut, esptool.ESPLoader):
#             self._esp = dut
#             self._stop_esptool_when_close = False
#         else:
#             self._esp = self._esptool_open_port(dut, **kwargs)
#         _esp_serial = _EspSerial(self._esp)
#         super().__init__(_esp_serial, name, log_file, **kwargs)
#         self._setup_esp()

#     def _setup_esp(self) -> None:
#         self._esp.hard_reset()

#     def har_reset(self) -> None:
#         self._esp.hard_reset()

#     def _esptool_path(self, use_esptool: str = '') -> str:
#         if use_esptool:
#             return use_esptool
#         return 'esptool.py'

#     def run_esptool(self, args, use_esptool: str = ''):
#         """Run esptool method with given args"""
#         _esptool = self._esptool_path(use_esptool)
#         with self.disable_redirect_thread():
#             esptool.main(args, esp=self._esp)
#             # Need to reset esp after running esptool
#             self._esp.hard_reset()


#     @property
#     def esp(self) -> esptool.ESPLoader:
#         return self._esp
