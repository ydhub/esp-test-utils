import contextlib
import os
import time

import esptool
import serial

import esptest.common.compat_typing as t

from ...common.encoding import to_bytes
from ...devices.esp_serial import EspPortInfo, detect_one_port, detect_port_info_no_cache, esptool_detect_chip
from ...devices.serial_tools import compute_serial_port, get_all_serial_ports, get_serial_port_info
from ...logger import get_logger

# from ...utility.parse_bin_path import ParseBinPath
from ...tools.download_bin import DownBinTool
from ..port.base_port import BasePort
from ..port.serial_port import SerialPort
from .download_log import (
    _download_device_from_config,
    _ports_equal,
    default_download_log_file,
    should_save_download_log,
)
from .dut_base import DutConfig

logger = get_logger('dut')


def log_port_hosts_esp(dut_config: DutConfig) -> bool:
    """Whether the log UART should host the persistent ``self.esp`` handle.

    ``support_esptool`` means hard_reset / download_bin may use esptool. The log
    port only gets an esp handle when it is the same serial device as
    ``download_device`` (or download is unset). Separate download/log UARTs keep a
    plain serial log port; flash/reset still go through ``download_device``.
    """
    if not dut_config.support_esptool:
        return False
    download = _download_device_from_config(dut_config)
    log_dev = str(dut_config.device or '')
    return bool(download and log_dev and _ports_equal(download, log_dev))


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
        self._download_port: t.Optional[SerialPort] = None
        super().__init__(*args, **kwargs)
        self._chip_info: t.Optional[EspPortInfo] = None

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
        # Only set when log UART hosts esp (download_device same as device).
        # Dual-UART: raw log port is serial; support_esptool still enables
        # hard_reset / download_bin via download_device.
        if isinstance(self.raw_port, EspSerial):
            return self.raw_port.esp
        return None

    @property
    def log_port(self) -> BasePort[t.Any]:
        if self._base_port_proxy:
            return self._base_port_proxy
        raise OSError('log_port is not available, port not configured')

    @property
    def download_port(self) -> SerialPort:
        if self._download_port:
            return self._download_port
        raise OSError('download_port is not available, port not configured')

    def _download_device(self) -> str:
        """Flash/download serial device (falls back to log ``device``)."""
        return _download_device_from_config(self.dut_config)

    @property
    def download_log_file(self) -> str:
        """Path used for download-UART serial + esptool logs (may be empty)."""
        if not should_save_download_log(self.dut_config):
            return ''
        if self._download_port is not None:
            port_log = getattr(self._download_port, 'log_file', '') or ''
            if isinstance(port_log, str) and port_log:
                return port_log
        return default_download_log_file(self.dut_config)

    def _append_download_log(self, text: str) -> None:
        log_file = self.download_log_file
        if not log_file:
            return
        parent = os.path.dirname(log_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as log_f:
            if text and not text.endswith('\n'):
                text = text + '\n'
            log_f.write(text)

    def _create_download_port(self) -> t.Optional[SerialPort]:
        """Open a SerialPort on download_device for side-channel logging."""
        if not should_save_download_log(self.dut_config):
            return None
        download = _download_device_from_config(self.dut_config)
        if not download:
            return None
        log_file = default_download_log_file(self.dut_config)
        if not log_file:
            return None
        # Persist resolved path on config for callers / DownBinTool.
        self.dut_config.download_log_file = log_file
        device = compute_serial_port(download, strict=False)
        serial_config = dict(self.dut_config.download_serial_configs or {})
        baudrate = int(serial_config.pop('baudrate', 115200) or 115200)
        serial_config['do_not_open'] = True
        raw = serial.serial_for_url(device, baudrate=baudrate, **serial_config)
        if serial_config.get('rtscts', True) is False:
            raw.rts = False  # type: ignore
            raw.dtr = False  # type: ignore
        raw.open()  # type: ignore
        name = f'{self.dut_config.name}_download'
        return SerialPort(raw, name=name, log_file=log_file)

    @contextlib.contextmanager
    def _borrow_download_port(self, reason: str) -> t.Generator[None, None, None]:
        """Release the download serial device for esptool, then restore monitors.

        - Dual-UART (``download_device`` != log ``device``): only pause the
          download-port side monitor; log UART redirect keeps running.
        - Same-port: also disable the log UART redirect thread so esptool can
          own the shared serial device.

        Appends begin/end markers to the download log when a side monitor exists.
        """
        download = _download_device_from_config(self.dut_config)
        log_dev = str(self.dut_config.device or '')
        same_port = bool(download and log_dev and _ports_equal(download, log_dev))
        log_cm: t.ContextManager[None]
        if same_port:
            log_cm = self.disable_redirect_thread()
        else:
            log_cm = contextlib.nullcontext()

        with log_cm:
            port = self._download_port
            if not port:
                yield
                return
            self._append_download_log(f'------------ {reason} begin (pause download monitor) ---------------')
            stopped = port.stop_redirect_thread()
            ser = port.serial
            was_open = bool(ser and ser.is_open)
            if was_open and ser is not None:
                ser.close()
            try:
                yield
            finally:
                if was_open and ser is not None and not ser.is_open:
                    ser.open()
                if stopped:
                    port.start_redirect_thread()
                self._append_download_log(f'------------ {reason} end (resume download monitor) ---------------')

    # esptool related methods
    def hard_reset(self) -> None:
        # Same-port + support_esptool: esp handle on log UART.
        if self.esp:
            self.esp.hard_reset()
            return
        # Dual-UART or serial log: reset via download port when esptool is enabled.
        download = _download_device_from_config(self.dut_config)
        if self.dut_config.support_esptool and download:
            with self._borrow_download_port('hard_reset'):
                logger.info(f'[{self.name}] hard reset: {download}')
                with esptool_detect_chip(download) as inst:
                    inst.hard_reset()
                    return
        raise OSError('hard reset is not available, esp or support_esptool/download device not set')

    def get_chip_info(self) -> EspPortInfo:
        """Read chip info via esptool (name, revision, mac, flash, ...).

        ``chip_rev_full`` is ``major * 100 + minor`` (same scale as bootloader
        ``min_rev_full`` / ``max_rev_full``); ``-1`` if unknown.

        Prefers ``get_serial_port_info`` + ``detect_one_port`` on the download port.
        If the download port cannot be listed locally, falls back to
        ``detect_port_info_no_cache`` (``self.esp`` when log hosts esp; otherwise the
        download device string). Only successful results are cached.

        Raises:
            OSError: when no device is configured, or detect / fallback fails.
        """
        if self._chip_info is not None:
            return self._chip_info
        device = _download_device_from_config(self.dut_config)
        if not device:
            raise OSError('get_chip_info is not available, no serial device configured')

        try:
            serial_info = get_serial_port_info(device)
        except serial.SerialException:
            serial_info = None

        with self._borrow_download_port('get_chip_info'):
            if serial_info is not None:
                info = detect_one_port(serial_info)
            elif self.esp:
                # esp is on the log port; invariant: same as download port
                info = detect_port_info_no_cache(self.esp.serial_port)
            else:
                info = detect_port_info_no_cache(device)
            if info.support_esptool:
                self._chip_info = info
                return self._chip_info
            raise OSError(
                f'get_chip_info failed on {info.device!r}: {info.chip_description or "esptool detect failed"}'
            )

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
            output_log=self.download_log_file,
        )
        if self.esp and (not self.esp.IS_STUB and self.esp.CHIP_NAME not in ['ESP32']):
            # always force no stub for these preview or dev targets
            self.downbin_tool.force_no_stub = True
        with self._borrow_download_port('download_bin'):
            self.downbin_tool.download()
        self.hard_reset()
        if log_port_baudrate:
            self.change_serial_config(baudrate=log_port_baudrate)

    def download_partition(self, partition_bins: t.Dict[str, str], baud: t.Union[int, t.List[int]] = 0) -> None:
        """Download partitions to the dut.
        Args:
            partition_bins: A dictionary of partition names and bin paths.
            baud: Download baud rate to use.
                If given a list, will try each baud rate in order.
        """
        if self.bin_path and not self.downbin_tool:
            self.downbin_tool = DownBinTool(
                str(self.bin_path),
                self.dut_config.download_device,
                esptool=self.dut_config.use_esptool,
                output_log=self.download_log_file,
            )
            if self.esp and (not self.esp.IS_STUB and self.esp.CHIP_NAME not in ['ESP32']):
                # always force no stub for these preview or dev targets
                self.downbin_tool.force_no_stub = True
        if not self.downbin_tool:
            raise ValueError('download_partition is not available, bin path not set')
        if self.download_log_file and not getattr(self.downbin_tool, 'output_log', ''):
            self.downbin_tool.output_log = self.download_log_file

        with self._borrow_download_port('download_partition'):
            self.downbin_tool.download_partition(partition_bins, baud=baud)
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
