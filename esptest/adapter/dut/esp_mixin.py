import time

import esptool
import serial

import esptest.common.compat_typing as t

from ...common.encoding import to_bytes
from ...devices.serial_tools import compute_serial_port, get_all_serial_ports

# from ...utility.parse_bin_path import ParseBinPath
from ...tools.download_bin import DownBinTool

if t.TYPE_CHECKING:
    # Do not import DutBase
    from .dut_base import DutBase

    BaseProtocol = DutBase
else:
    BaseProtocol = object


class EspSerial:
    """Add RawPort methods to esp serial"""

    def __init__(self, esp: esptool.ESPLoader) -> None:
        self._esp = esp
        self._serial: serial.Serial = esp._port

    @property
    def esp(self) -> esptool.ESPLoader:
        return self._esp

    @property
    def read_timeout(self) -> float:
        # For PortSpawn
        return self._serial.timeout or 0.001  # type: ignore

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
    def _esptool_open_port(self, port: str, initial_baud: int, **kwargs: t.Any) -> esptool.ESPLoader:
        port = compute_serial_port(port) if port else ''
        serial_list = [port] if port else [p.device for p in get_all_serial_ports()]
        # esptool.get_default_connected_device always detect_chip from serial_list
        esp = esptool.get_default_connected_device(
            serial_list,
            port=port or None,  # type: ignore
            connect_attempts=3,
            initial_baud=initial_baud,
            chip=kwargs.get('chip', 'auto'),
        )
        assert esp, f'Failed to connect to {port}'
        return esp

    def _esptool_path(self, use_esptool: str = '') -> str:
        if use_esptool:
            return use_esptool
        return 'esptool.py'

    @property
    def esp(self) -> esptool.ESPLoader:
        if isinstance(self.raw_port, EspSerial):
            return self.raw_port.esp
        return None

    # esptool related methods
    def hard_reset(self) -> None:
        if self.esp:
            self.esp.hard_reset()
            return
        # try to use esptool for serial devices
        if self.dut_config.device:
            with self.disable_redirect_thread():
                with esptool.detect_chip(self.dut_config.device) as inst:
                    inst.hard_reset()
                    return
        raise NotImplementedError()

    def download_bin(self, erase_nvs: bool = True) -> None:
        if not self.bin_path:
            raise NotImplementedError('bin path must be set before using this method!')
        down_bin_tool = DownBinTool(
            str(self.bin_path),
            self.dut_config.download_device,
            esptool=self.dut_config.use_esptool,
            erase_nvs=erase_nvs,
        )
        if not self.esp.IS_STUB and self.esp.CHIP_NAME not in ['ESP32']:
            # preview or dev targets
            down_bin_tool.force_no_stub = True
        with self.disable_redirect_thread():
            down_bin_tool.download()
        self.hard_reset()

    def start_redirect_thread(self) -> None:
        if self.esp:
            self.esp._port.open()  # pylint: disable=protected-access
            if self.log_file:
                with open(self.log_file, 'a', encoding='utf-8') as log_f:
                    log_f.write(
                        f'------------ reopen port: {self.esp._port.port} {self.esp._port.baudrate} --------------- \n'  # pylint: disable=protected-access
                    )
        super().start_redirect_thread()

    def stop_redirect_thread(self) -> bool:
        if self.esp:
            if not self.esp._port.is_open:  # pylint: disable=protected-access
                return False
        super().stop_redirect_thread()
        if self.esp:
            self.esp._port.close()  # pylint: disable=protected-access
        return True
