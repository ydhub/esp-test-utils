import contextlib
import logging
import os
import re
from dataclasses import dataclass
from logging import Formatter
from pathlib import Path
from typing import overload

from esptool.loader import ESPLoader

import esptest.common.compat_typing as t

from ...common.timestamp import timestamp_str
from ...interface.dut import DutInterface
from ...interface.port import PortInterface
from ...logger import get_logger
from ...utility.parse_bin_path import ParseBinPath, get_baud_from_bin_path
from ..port.base_port import BasePort, RawPort
from ..port.serial_port import SerialPort

logger = get_logger('dut')
DEFAULT_SERIAL_CONFIGS = {'timeout': 0.005}


@dataclass
class DutConfig:
    name: str = ''  # default = dut name / port name
    device: str = ''  # log serial device, eg: '/dev/ttyUSB0', 'COM3', etc.
    baudrate: int = 0  # 0: get from bin path or 115200
    serial_configs: t.Optional[t.Dict[str, t.Any]] = None  # serial configs, eg: {'bytesize': 8, 'timeout': 0.1}
    # capabilities
    support_esptool: bool = False  # esp port or serial port
    esptool_stub: bool = True  # Try to get stub from bin_path if bin_path was set
    esptool_chip: str = 'auto'  # Try to get chip from bin_path if bin_path was set
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
        # serial configs
        _serial_configs = DEFAULT_SERIAL_CONFIGS.copy()
        if self.serial_configs:
            _serial_configs.update(self.serial_configs)
        self.serial_configs = _serial_configs
        # bin_path and get variables from bin path
        if self.bin_path:
            self.bin_path = Path(self.bin_path).expanduser().resolve()
            self.esptool_stub = ParseBinPath(self.bin_path).stub
            self.esptool_chip = ParseBinPath(self.bin_path).chip
            if not self.baudrate:
                self.baudrate = get_baud_from_bin_path(self.bin_path) or 115200
        # download device
        if not self.download_device:
            self.download_device = self.device

    def _auto_gen_name(self) -> None:
        if self.opened_port:
            if isinstance(self.opened_port, SerialPort):
                self.device = self.opened_port.raw_port.device
                self.name = self.opened_port.name
            elif isinstance(self.opened_port, BasePort):
                self.name = self.opened_port.name
        if not self.name:
            if self.device:
                self.name = os.path.basename(self.device)
        assert self.name, 'DutConfig "name" must be set'

    @property
    def serial_read_timeout(self) -> float:
        assert isinstance(self.serial_configs, dict)
        assert 'timeout' in self.serial_configs
        return float(self.serial_configs['timeout'])  # type: ignore


class VariablesMixin:
    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        self._variables: t.Dict[str, t.Any] = {}
        self._dynamic_variables: t.Dict[str, t.Any] = {}
        super().__init__(*args, **kwargs)

    def get_variable_by_name(self, name: str, default: t.Any = None) -> t.Any:
        if name in self._dynamic_variables:
            return self._dynamic_variables[name]
        if name in self._variables:
            return self._variables[name]
        return default

    def add_variable(self, name: str, value: t.Any) -> None:
        self._variables[name] = value

    def remove_variable(self, name: str) -> None:
        if name in self._variables:
            self._variables.pop(name)

    def add_dynamic_variable(self, name: str, value: t.Any) -> None:
        self._dynamic_variables[name] = value

    def remove_dynamic_variable(self, name: str) -> None:
        if name in self._dynamic_variables:
            self._dynamic_variables.pop(name)


class DutBase(VariablesMixin, DutInterface):  # pylint: disable=too-many-public-methods
    """A base Dut class"""

    BASE_PORT_PROXY_METHODS = list(PortInterface.__abstractmethods__)

    def __init__(self, *, dut_config: DutConfig, **kwargs: t.Any) -> None:
        super().__init__(**kwargs)
        # args and kwargs may be used by mixins
        self._dut_config: DutConfig = dut_config
        self._kwargs = kwargs
        self._raw_port: t.Optional[RawPort] = None
        self._base_port_proxy: t.Optional[BasePort] = None
        self._dut_logger: logging.Logger = self._create_dut_logger()
        # update variables / fields, open ports, logging
        self._post_init()
        # flash thread
        self.setup_dut()
        # redirect thread
        self._start()

    def _create_dut_logger(self) -> logging.Logger:
        return logger.getChild(self.name)

    def _post_init(self) -> None:
        """Update variables"""
        pass  # pylint: disable=unnecessary-pass

    def setup_dut(self) -> None:
        """Flash / hard reset"""
        pass  # pylint: disable=unnecessary-pass

    def _start(self) -> None:
        pass

    @property
    def dut_config(self) -> DutConfig:
        return self._dut_config

    @property
    def dut_logger(self) -> logging.Logger:
        return self._dut_logger

    @property
    def target(self) -> str:
        # child class should implement this method
        return 'unknown'

    @property
    def esp(self) -> ESPLoader:
        """Not all Dut support this method"""
        raise NotImplementedError()

    def close(self) -> None:
        pass

    def __enter__(self) -> 't.Self':
        return self

    def __exit__(self, exc_type, exc_value, trace) -> None:  # type: ignore
        self.close()

    # bin path related methods
    @property
    def bin_path(self) -> t.Union[str, Path]:
        return self.dut_config.bin_path

    @property
    def sdkconfig(self) -> t.Dict[str, t.Any]:
        if not self.bin_path:
            raise FileNotFoundError('Can not get sdkconfig, bin_path is not set.')
        return ParseBinPath(self.bin_path).sdkconfig

    # esptool related methods
    def hard_reset(self) -> None:
        raise NotImplementedError()

    def flash(self, erase_nvs: bool = True) -> None:
        raise NotImplementedError()

    def flash_partition(self, part: t.Union[int, str], bin_file: str = '') -> None:
        raise NotImplementedError()

    def dump_flash(self, part: t.Union[int, str], bin_file: str, size: int = 0) -> None:
        raise NotImplementedError()

    # port base methods, use the proxy method if possible, otherwise, child class should implement them
    # def __getattribute__(self, name: str) -> t.Any:
    #     if object.__getattribute__(self, '_base_port_proxy'):
    #         if name in object.__getattribute__(self, 'BASE_PORT_PROXY_METHODS'):
    #             return getattr(self._base_port_proxy, name)
    #     return object.__getattribute__(self, name)

    @property
    def raw_port(self) -> t.Any:
        if self._base_port_proxy:
            return self._base_port_proxy.raw_port
        raise NotImplementedError()

    @property
    def name(self) -> t.Any:
        return self.dut_config.name

    @name.setter
    def name(self, value: str) -> None:
        raise NotImplementedError()

    def write(self, data: t.AnyStr) -> None:
        if self._base_port_proxy:
            return self._base_port_proxy.write(data)
        raise NotImplementedError()

    def write_line(self, data: t.AnyStr, end: str = '\n') -> None:
        if self._base_port_proxy:
            return self._base_port_proxy.write_line(data, end)
        raise NotImplementedError()

    @overload
    def expect(self, pattern: str, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: bytes, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: re.Pattern[str], timeout: float = 30) -> re.Match[str]: ...
    @overload
    def expect(self, pattern: re.Pattern[bytes], timeout: float = 30) -> re.Match[bytes]: ...

    def expect(self, pattern, timeout=30):  # type: ignore
        if self._base_port_proxy:
            return self._base_port_proxy.expect(pattern, timeout)
        raise NotImplementedError()

    @property
    def data_cache(self) -> str:
        return self.read_all_data(flush=False)

    def flush_data(self) -> str:
        return self.read_all_data(flush=True)

    def read_all_data(self, flush: bool = True) -> str:
        if self._base_port_proxy:
            return self._base_port_proxy.read_all_data(flush)
        raise NotImplementedError()

    def read_all_bytes(self, flush: bool = False) -> bytes:
        if self._base_port_proxy:
            return self._base_port_proxy.read_all_bytes(flush)
        raise NotImplementedError()

    def start_redirect_thread(self) -> None:
        """Start a new thread to read data from port and save to data cache."""
        if self._base_port_proxy:
            return self._base_port_proxy.start_redirect_thread()
        raise NotImplementedError()

    def stop_redirect_thread(self) -> bool:
        """Stop the redirect thread and pexpect process."""
        if self._base_port_proxy:
            return self._base_port_proxy.stop_redirect_thread()
        raise NotImplementedError()

    @contextlib.contextmanager
    def disable_redirect_thread(self) -> t.Generator[None, None, None]:
        stopped = self.stop_redirect_thread()
        yield
        if stopped:
            self.start_redirect_thread()
