import logging
import os
from dataclasses import dataclass
from logging import Formatter
from pathlib import Path

import esptest.common.compat_typing as t

from ...common.timestamp import timestamp_str
from ...devices.serial_tools import compute_serial_port
from ...logger import get_logger
from ...utility.parse_bin_path import get_baud_from_bin_path
from ..port.base_port import BasePort, RawPort
from ..port.serial_port import SerialExt

logger = get_logger('dutbase')


@dataclass
class DutConfig:
    name: str = ''  # default = dut name / port name
    device: str = ''  # log serial device, eg: '/dev/ttyUSB0', 'COM3', etc.
    baudrate: int = 0  # 0: get from bin path or 115200
    serial_configs: t.Optional[t.Dict[str, t.Any]] = None  # serial configs, eg: {'bytesize': 8, 'timeout': 0.1}
    # capabilities
    support_esptool: bool = True  # esp port or serial port
    create_redirect_thread: bool = True  # create redirect thread or not
    # create dut from open serial/raw_port/others
    opened_port: t.Any = None
    # download bin
    bin_path: t.Union[str, Path] = ''
    use_esptool: str = ''  # For FPGA, use specific esptool
    download_device: str = ''  # default = base port device
    download_baudrate: int = 0  # default ESPBAUD
    # dut (uart) log
    log_path: t.Union[str, Path] = ''  # default
    log_file: str = ''  # default: auto-generate  log_path + <name>[_<second>]_<timestamp>.log
    rx_log_formater: t.Optional[Formatter] = None
    tx_log_formater: t.Optional[Formatter] = None
    logger: t.Optional[logging.Logger] = None
    # callback  (data, dut_name)
    tx_log_callback: t.Optional[t.Callable[[str, bytes, str], None]] = None
    rx_log_callback: t.Optional[t.Callable[[str, bytes, str], None]] = None
    # monitor
    monitors: t.Optional[object] = None
    # checkers
    pexpect_timeout: float = 30  # default pexpect timeout]
    # extra / customer args
    kwargs: t.Optional[t.Dict[str, t.Any]] = None

    def __post_init__(self) -> None:
        self._auto_gen_name()
        if not self.log_file:
            _log_path = self.log_path or './dut_logs'
            _file_name = f'{self.name}_{timestamp_str()}.log'.replace(':', '-')
            self.log_file = str(Path(_log_path) / _file_name)

    def _auto_gen_name(self) -> None:
        if self.opened_port:
            if isinstance(self.opened_port, BasePort):
                logger.info('')
                self.name = self.opened_port.name
        if not self.name:
            if self.device:
                self.name = os.path.basename(self.device)
        assert self.name, 'DutConfig "name" must be set'


class DutBase(BasePort):
    """Add dut related methods to Port"""

    def __init__(self, dut_config: DutConfig, *args: t.Any, **kwargs: t.Any) -> None:
        # args and kwargs may be used by mixins
        self._dut_config = dut_config
        self._args = args  # ignore args
        self._kwargs = kwargs
        # __enter__ and __exit__
        self._close_redirect_thread_when_exit = True
        self._close_raw_port_when_exit = True
        self._close_download_port_when_exit = False
        # create base port / log port
        # init base class
        _raw_port = self._create_raw_port()
        # do not pass dut_config/name/log_file to parent classes
        super().__init__(_raw_port, **self._kwargs)

    def _post_init(self) -> None:
        self._name = self._dut_config.name
        super()._post_init()

    @property
    def dut_config(self) -> DutConfig:
        return self._dut_config

    def _create_raw_port(self) -> RawPort:
        _config = self._dut_config
        _raw_port = None
        if _config.opened_port:
            if isinstance(_config.opened_port, RawPort):
                _raw_port = _config.opened_port
                self._close_raw_port_when_exit = False
                return _raw_port
            # TODO: create from BasePort
            raise TypeError(f'Can not create dut from {type(_config.opened_port)}')
        # create serial port
        assert _config.device, 'No device provided in DutConfig'
        _device = compute_serial_port(_config.device, strict=True)
        _baudrate = _config.baudrate or get_baud_from_bin_path(_config.bin_path) or 115200
        self._close_raw_port_when_exit = True
        return SerialExt(port=_device, baudrate=_baudrate, **(_config.serial_configs or {}))

    def close(self) -> None:
        if self._close_redirect_thread_when_exit:
            self.stop_redirect_thread()
        if self._close_raw_port_when_exit:
            self._raw_port.close()

    def __enter__(self) -> 't.Self':
        return self

    def __exit__(self, exc_type, exc_value, trace) -> None:  # type: ignore
        self.close()

    # Attributes needed by bin path
    @property
    def bin_path(self) -> t.Union[str, Path]:
        return self._dut_config.bin_path

    @property
    def sdkconfig(self) -> t.Dict[str, t.Any]:
        raise NotImplementedError()

    @property
    def target(self) -> str:
        raise NotImplementedError()

    @property
    def partition_table(self) -> t.Dict[str, t.Any]:
        raise NotImplementedError()

    # Serial Specific
    def reconfigure(self) -> bool:
        raise NotImplementedError()

    def hard_reset(self) -> None:
        raise NotImplementedError()

    # EspTool Specific
    def flash(self, bin_path: str = '') -> None:
        raise NotImplementedError()

    def flash_partition(self, part: t.Union[int, str], bin_path: str = '') -> None:
        raise NotImplementedError()

    def flash_nvs(self, bin_path: str = '') -> None:
        raise NotImplementedError()

    def dump_flash(self, part: t.Union[int, str], bin_path: str, size: int = 0) -> None:
        raise NotImplementedError()

    # More extra methods may be implemented
