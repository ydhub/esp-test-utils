import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import esptest.common.compat_typing as t

IDF_PATH = os.getenv('IDF_PATH', '')
logger = logging.getLogger('parse_bin_path')


def get_baud_from_bin_path(bin_path: t.Union[str, Path]) -> int:
    """Get baudrate from binary path, if available. return 0 if failed"""
    if not bin_path:
        return 0  # Failed to get baudrate
    try:
        sdkconfig_file = Path(bin_path) / 'sdkconfig'
        with open(str(sdkconfig_file), 'r', encoding='utf-8') as f:
            data = f.read()
            match = re.search(r'CONSOLE_UART_BAUDRATE=(\d+)', data)
            if match:
                return int(match.group(1))
    except OSError:
        # FileExistsError, FileNotFoundError, etc.
        pass
    try:
        sdkconfig_json_file = Path(bin_path) / 'config' / 'sdkconfig.json'
        with open(str(sdkconfig_json_file), 'r', encoding='utf-8') as f:
            json_data: t.Dict[str, t.Any] = json.load(f)
            for key in ['ESP_CONSOLE_UART_BAUDRATE', 'CONSOLE_UART_BAUDRATE']:
                if key in json_data.keys():
                    return int(json_data[key])
    except OSError:
        # FileExistsError, FileNotFoundError, etc.
        pass
    return 0  # Failed to get baudrate


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
        self.flasher_args = self.parse_flash_args()
        self.stub: bool = self.flasher_args['extra_esptool_args'].get('stub', False)
        self.chip: str = self.flasher_args['extra_esptool_args'].get('chip', 'auto')

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
        return ''

    def parse_flash_args(self) -> t.Dict[str, t.Any]:
        """Parse flash args from flasher_args.json"""
        flasher_args_file = Path(self.bin_path) / self.FLASHER_ARGS_FILE
        _flasher_args = {}
        try:
            with open(str(flasher_args_file), 'r', encoding='utf-8') as f:
                _flasher_args = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _flasher_args = {}
        return _flasher_args

    def _gen_partition_table(self) -> None:
        part_csv = Path(self.bin_path) / 'partition_table' / 'partition-table.csv'
        part_bin = Path(self.bin_path) / 'partition_table' / 'partition-table.bin'
        if self.parttool_path and not part_csv.is_file() and part_bin.is_file():
            try:
                _cmd = f'python {self.parttool_path} {str(part_bin)} {str(part_csv)}'
                subprocess.check_call(_cmd)
            except subprocess.SubprocessError as e:
                logger.error(f'Failed to gen partition-table.csv: {str(e)}')

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
        args += ['--after', self.flasher_args['extra_esptool_args']['after']]
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

    def flash_bin_args(self, baudrate: int = 0, erase_nvs: bool = True) -> t.List[str]:
        """Get write_flash args / command for esptool"""
        args = self._write_flash_args_common(baudrate)
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
