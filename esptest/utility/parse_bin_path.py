import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import esptest.common.compat_typing as t

IDF_PATH = os.getenv('IDF_PATH', '')
logger = logging.getLogger('parse_bin_path')
DEFAULT_GEN_PART_TOOL = os.path.join(os.path.dirname(__file__), 'gen_esp32part.py')


def get_baud_from_bin_path(bin_path: t.Union[str, Path]) -> int:
    """Get baudrate from binary path, if available. return 0 if failed"""
    if not bin_path or not Path(bin_path).is_dir():
        # Never raise error from this method
        return 0
    try:
        return ParseBinPath(bin_path).sdkconfig.console_baud
    except (OSError, AssertionError):
        # no sdkconfig file or sdkconfig file is not valid
        return 0


class SDKConfig(t.Dict[str, t.Any]):
    """A class to represent SDK configuration"""

    CONSOLE_BAUD_KEYS = [
        'ESP_CONSOLE_UART_BAUDRATE',
        'CONSOLE_UART_BAUDRATE',
        'ESPTOOLPY_MONITOR_BAUD',
    ]

    @classmethod
    def from_file(cls, sdkconfig_file: t.Union[str, Path]) -> 'SDKConfig':
        """Load SDK config from a file"""
        sdkconfig = cls()
        sdkconfig_file = Path(sdkconfig_file)
        with sdkconfig_file.open('r', encoding='utf-8') as f:
            if sdkconfig_file.suffix == '.json':
                sdkconfig.update(json.load(f))
            else:
                # text sdkconfig
                for line in f.readlines():
                    if line.startswith('CONFIG_') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip().removeprefix('CONFIG_')
                        value = value.strip()
                        sdkconfig[key] = (
                            True
                            if value == 'y'
                            else False
                            if value == 'n'
                            else int(value)
                            if value.isdigit()
                            else value[1:-1]
                            if value[0] == '"'
                            else value
                        )
                    elif line.startswith('# CONFIG_') and line.strip().endswith(' is not set'):
                        key = line.strip().removeprefix('# CONFIG_').removesuffix(' is not set')
                        sdkconfig[key] = False
                        continue
        return sdkconfig

    @property
    def console_baud(self) -> int:
        """Get baudrate from SDK config"""
        assert self, 'SDKConfig is not initialized'
        for key in self.CONSOLE_BAUD_KEYS:
            if key in self:
                return int(self[key])
        logger.warning('failed to get baud from sdkconfig')
        return 0

    @property
    def flash_encryption(self) -> bool:
        """Get flash encryption status from SDK config"""
        assert self, 'SDKConfig is not initialized'
        if 'SECURE_FLASH_ENC_ENABLED' not in self:
            logger.warning('SECURE_FLASH_ENC_ENABLED not found in sdkconfig')
        return bool(self.get('SECURE_FLASH_ENC_ENABLED', False))


@dataclass
class PartitionInfo:
    name: str
    type: str
    subtype: str
    offset: str
    size: int
    flags: str


class ParseBinPath:
    """Flash args for esptool.py"""

    FLASHER_ARGS_FILE = 'flasher_args.json'

    def __init__(
        self,
        bin_path: t.Union[str, Path],
        parttool: str = '',
    ):
        self.bin_path = str(bin_path)
        self._parttool = parttool
        self._parttool = parttool
        self._flasher_args: t.Dict[str, t.Any] = {}
        self._sdkconfig: SDKConfig = SDKConfig()

    @property
    def sdkconfig(self) -> SDKConfig:
        """
        Returns:
            sdkconfig object
        """
        if not self._sdkconfig:
            sdkconfig_file = Path(self.bin_path) / 'config' / 'sdkconfig.json'
            if sdkconfig_file.is_file():
                self._sdkconfig = SDKConfig.from_file(sdkconfig_file)
            else:
                sdkconfig_file = Path(self.bin_path) / 'sdkconfig'
                if sdkconfig_file.is_file():
                    self._sdkconfig = SDKConfig.from_file(sdkconfig_file)
                else:
                    raise FileNotFoundError("'sdkconfig.json' or 'sdkconfig' not found in bin path")
        return self._sdkconfig

    @property
    def parttool_path(self) -> str:
        """
        Returns:
            Partition tool (gen_esp32part.py) path
        """
        if self._parttool:
            return os.path.realpath(self._parttool)
        if IDF_PATH:
            _parttool = str(Path(IDF_PATH) / 'components' / 'partition_table' / 'gen_esp32part.py')
            if os.path.isfile(_parttool):
                return os.path.realpath(_parttool)
        return DEFAULT_GEN_PART_TOOL

    @staticmethod
    def _parse_flash_args(flasher_args_file: t.Union[str, Path]) -> t.Dict[str, t.Any]:
        _flasher_args = {}
        try:
            with open(str(flasher_args_file), 'r', encoding='utf-8') as f:
                _flasher_args = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _flasher_args = {}
        return _flasher_args

    @property
    def flasher_args(self) -> t.Dict[str, t.Any]:
        """Parse flash args from flasher_args.json"""
        if not self._flasher_args:
            flasher_args_file = Path(self.bin_path) / self.FLASHER_ARGS_FILE
            self._flasher_args = self._parse_flash_args(flasher_args_file)
        return self._flasher_args

    @property
    def chip(self) -> str:
        """Check the current chip"""
        return str(self.flasher_args['extra_esptool_args'].get('chip', 'auto'))

    @property
    def stub(self) -> bool:
        """Check if esptool stub is used"""
        return bool(self.flasher_args['extra_esptool_args'].get('stub', False))

    def _gen_partition_table(self) -> None:
        part_csv = Path(self.bin_path) / 'partition_table' / 'partition-table.csv'
        part_bin = Path(self.bin_path) / 'partition_table' / 'partition-table.bin'
        if self.parttool_path and not part_csv.is_file() and part_bin.is_file():
            try:
                _cmd = f'python {self.parttool_path} {str(part_bin)} {str(part_csv)}'
                subprocess.check_call(_cmd, shell=True)
            except subprocess.SubprocessError as e:
                logger.error(f'Failed to gen partition-table.csv: {str(e)}')

    @lru_cache()
    def parse_partitions(self) -> t.List[PartitionInfo]:
        """Parse partitions from partition-table.csv"""
        self._gen_partition_table()
        partition_table_file = Path(self.bin_path) / 'partition_table' / 'partition-table.csv'
        if not partition_table_file.is_file():
            raise ValueError('Can not parse partition table')
        # # Name, Type, SubType, Offset, Size, Flags
        # nvs,data,nvs,0x9000,24K,
        # phy_init,data,phy,0xf000,4K,
        # factory,app,factory,0x10000,2M,
        partitions: t.List[PartitionInfo] = []
        try:
            with open(str(partition_table_file), 'r', encoding='utf-8') as f:
                for line in f.readlines():
                    sections = line.strip().split(',')
                    if line.startswith('#') or len(sections) != 6:
                        continue
                    _size_str = sections[4]
                    _size = 0
                    if _size_str.endswith('K'):
                        _size = int(_size_str[:-1]) * 1024
                    elif _size_str.endswith('M'):
                        _size = int(_size_str[:-1]) * 1024 * 1024
                    elif _size_str.startswith('0x'):
                        _size = int(_size_str, 16)
                    else:
                        _size = int(_size_str)
                    partitions.append(
                        PartitionInfo(
                            sections[0],
                            sections[1],
                            sections[2],
                            sections[3],
                            _size,
                            sections[5],
                        )
                    )
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return partitions

    def _write_flash_args_common(self, baudrate: int = 0) -> t.List[str]:
        args = []
        if baudrate:
            args += ['-b', str(baudrate)]
        args += ['--chip', self.chip]
        args += ['--before', self.flasher_args['extra_esptool_args']['before']]
        # idf build will force `--after=no_rest` for secure boot or flash encryption
        # but this was not a expected for testing
        args += ['--after', 'hard_reset']
        if not self.stub:
            args += ['--no-stub']
        args += ['write_flash']
        args += self.flasher_args['write_flash_args']
        return args

    def _gen_erase_nvs_bin(self) -> t.Tuple[str, str]:
        """generate bin file for erasing nvs partition

        Returns:
            t.Tuple[str, str]: <offset>, <nvs_bin_path>
        """

        for part in self.parse_partitions():
            if part.name != 'nvs':
                continue
            nvs_bin = tempfile.mktemp()
            with open(nvs_bin, 'wb+') as f:
                f.write(b'\xff' * part.size)
            return part.offset, nvs_bin
        raise ValueError('Can not get nvs partition info')

    def erase_flash_args(self, baudrate: int = 0) -> t.List[str]:
        args = []
        if baudrate:
            args += ['-b', str(baudrate)]
        args += ['--chip', self.chip]
        args += ['--before', self.flasher_args['extra_esptool_args']['before']]
        args += ['--after', self.flasher_args['extra_esptool_args']['after']]
        if not self.stub:
            args += ['--no-stub']
        args += ['erase_flash']
        return args

    def flash_bin_args(self, baudrate: int = 0, erase_nvs: bool = True, encrypted: bool = False) -> t.List[str]:
        """Get write_flash args / command for esptool.

        Args:
            baudrate (int, optional): baudrate for flashing.
            erase_nvs (bool, optional): whether to erase nvs partition.
            encrypted (bool, optional): whether to flash with encryption.
        """
        args = self._write_flash_args_common(baudrate)
        if encrypted:
            args += ['--encrypt']
        for offset, bin_file in self.flasher_args['flash_files'].items():
            args += [offset, str(Path(self.bin_path) / bin_file)]
        if erase_nvs:
            args += list(self._gen_erase_nvs_bin())
        return args

    def flash_nvs_args(self, nvs_bin: str = '') -> list[str]:
        args = self._write_flash_args_common()
        for part in self.parse_partitions():
            if part.name != 'nvs':
                continue
            # write nvs
            if nvs_bin:
                return args + [part.offset, nvs_bin]
            # erase nvs
            return args + list(self._gen_erase_nvs_bin())
        raise ValueError('Can not find nvs partition info')

    def get_partition_info(self, part_name: str) -> PartitionInfo:
        for part in self.parse_partitions():
            if part.name == part_name:
                return part
        raise ValueError('Can not find nvs partition info')
