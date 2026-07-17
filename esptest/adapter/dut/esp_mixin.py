import time

import esptool
import serial

import esptest.common.compat_typing as t

from ...common.encoding import to_bytes
from ...devices.serial_tools import compute_serial_port, get_all_serial_ports
from ...logger import get_logger

# from ...utility.parse_bin_path import ParseBinPath
from ...tools.download_bin import DownBinTool

logger = get_logger('dut')

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
    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        self.downbin_tool: t.Optional[DownBinTool] = None
        super().__init__(*args, **kwargs)

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
        raise OSError('hard reset is not available, esp or serial device not set')

    def change_serial_config(self, **kwargs: t.Any) -> None:
        """Change the underlying serial config (baudrate/timeout/parity/...).

        For an esptool-backed port the settings are applied to the esp serial port;
        otherwise the request is delegated to the serial port proxy.
        Only settings supported by pyserial ``apply_settings`` take effect.
        """
        if not self.esp:
            super().change_serial_config(**kwargs)
            return
        # Stop the redirect thread first to avoid racing with the background reader
        # while the port is being reconfigured.
        with self.disable_redirect_thread():
            self.esp._port.apply_settings(kwargs)  # pylint: disable=protected-access
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as log_f:
                log_f.write(
                    f'------------ change serial config: {self.esp._port.port} {kwargs} --------------- \n'  # pylint: disable=protected-access
                )

    def download_bin(
        self,
        erase_nvs: bool = True,
        *,
        bin_path: str = '',
        baud: t.Union[int, t.List[int]] = 0,
        force_no_stub: bool = False,
        log_port_baudrate: int = 0,
    ) -> None:
        """Download bin to the dut. Note: this method will update downbin_tool attribute.

        Args:
            erase_nvs (bool, optional): Whether to erase nvs before flashing.
            bin_path (str, optional): Path to the bin file, overwrite the bin_path attribute if provided.
            baud (Union[int, List[int]], optional): Download baud rate to use.
                If given a list, will try each baud rate in order.
            force_no_stub (bool, optional): Whether to force no stub.
            log_port_baudrate (int, optional): If > 0, set the log/monitor serial port
                baud rate after downloading.
        """
        if bin_path:
            if self.bin_path:
                logger.warning(f'[{self.name}] bin path will be overwritten by download_bin: {bin_path}')
            self.dut_config.bin_path = bin_path
        if not self.bin_path:
            raise ValueError('download_bin is not available, bin path not set')
        self.downbin_tool = DownBinTool(
            str(self.bin_path),
            self.dut_config.download_device,
            esptool=self.dut_config.use_esptool,
            erase_nvs=erase_nvs,
            baud=baud,
            force_no_stub=force_no_stub,
        )
        if self.esp and (not self.esp.IS_STUB and self.esp.CHIP_NAME not in ['ESP32']):
            # always force no stub for these preview or dev targets
            self.downbin_tool.force_no_stub = True
        with self.disable_redirect_thread():
            self.downbin_tool.download()
        self.hard_reset()
        if log_port_baudrate:
            self.change_serial_config(baudrate=log_port_baudrate)

    def download_partition(self, partition_bins: t.Dict[str, str]) -> None:
        """Download partitions to the dut.
        Args:
            partition_bins: A dictionary of partition names and bin paths.
        """
        if self.bin_path and not self.downbin_tool:
            self.downbin_tool = DownBinTool(
                str(self.bin_path),
                self.dut_config.download_device,
                esptool=self.dut_config.use_esptool,
            )
            if self.esp and (not self.esp.IS_STUB and self.esp.CHIP_NAME not in ['ESP32']):
                # always force no stub for these preview or dev targets
                self.downbin_tool.force_no_stub = True
        if not self.downbin_tool:
            raise ValueError('download_partition is not available, bin path not set')

        with self.disable_redirect_thread():
            self.downbin_tool.download_partition(partition_bins)
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
        # Always stop spawn first. A closed serial port must not skip this,
        # or expect() will keep seeing a missing redirect after flash failures.
        stopped = super().stop_redirect_thread()
        if self.esp and self.esp._port.is_open:  # pylint: disable=protected-access
            self.esp._port.close()  # pylint: disable=protected-access
            stopped = True
        return stopped
