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
from ...utility.parse_bin_path import ParseBinPath
from ..port.base_port import BasePort, RawPort

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


class DutBase(DutInterface):
    """A base Dut class"""

    BASE_PORT_PROXY_METHODS = list(PortInterface.__abstractmethods__)

    def __init__(self, *, dut_config: DutConfig, **kwargs: t.Any) -> None:
        # args and kwargs may be used by mixins
        self._dut_config = dut_config
        self._kwargs = kwargs
        self._raw_port: t.Optional[RawPort] = None
        self._base_port_proxy: t.Optional[BasePort] = None
        self._post_init()
        self._start()

    def _post_init(self) -> None:
        self._name = self._dut_config.name

    def _start(self) -> None:
        pass

    @property
    def dut_config(self) -> DutConfig:
        return self._dut_config

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
    def __getattribute__(self, name: str) -> t.Any:
        if object.__getattribute__(self, '_base_port_proxy'):
            if name in object.__getattribute__(self, 'BASE_PORT_PROXY_METHODS'):
                return getattr(self._base_port_proxy, name)
        return object.__getattribute__(self, name)

    @property
    def raw_port(self) -> t.Any:
        raise NotImplementedError()

    @property
    def name(self) -> t.Any:
        return self.dut_config.name

    @name.setter
    def name(self, value: str) -> None:
        raise NotImplementedError()

    def write(self, data: t.AnyStr) -> None:
        raise NotImplementedError()

    def write_line(self, data: t.AnyStr, end: str = '\n') -> None:
        raise NotImplementedError()

    @overload
    def expect(self, pattern: str, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: bytes, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: re.Pattern[str], timeout: float = 30) -> re.Match[str]: ...
    @overload
    def expect(self, pattern: re.Pattern[bytes], timeout: float = 30) -> re.Match[bytes]: ...

    def expect(self, pattern, timeout=0):  # type: ignore
        raise NotImplementedError()

    @property
    def data_cache(self) -> str:
        return self.read_all_data(flush=False)

    def flush_data(self) -> str:
        return self.read_all_data(flush=True)

    def read_all_data(self, flush: bool = True) -> str:
        raise NotImplementedError()

    def read_all_bytes(self, flush: bool = False) -> bytes:
        raise NotImplementedError()
