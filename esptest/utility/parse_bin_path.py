import json
import logging
import os
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import esptest.common.compat_typing as t

# pylint 在将 utility 视为顶层时判定“相对导入越级”，故禁用此检查
from ..tools.http_download import download_file  # pylint: disable=relative-beyond-top-level

IDF_PATH = os.getenv('IDF_PATH', '')
logger = logging.getLogger('parse_bin_path')
DEFAULT_GEN_PART_TOOL = os.path.join(os.path.dirname(__file__), 'gen_esp32part.py')


@lru_cache()
def _tmp_dir() -> str:
    return tempfile.mkdtemp()


@lru_cache()
def bin_path_to_dir(bin_path: str) -> str:
    bin_hash = hash(bin_path)
    bin_base_name = os.path.basename(bin_path)
    if bin_path.startswith('http'):
        assert bin_path.endswith('.zip')  # for now only support zip from url
        new_bin_path = os.path.join(_tmp_dir(), f'{bin_hash}', bin_base_name)
        os.makedirs(os.path.dirname(new_bin_path), exist_ok=True)
        download_file(bin_path, new_bin_path)
        bin_path = new_bin_path
    if bin_path.endswith('.zip'):
        logger.warning(f'bin path {bin_path} is not a directory, trying to convert to directory')
        if hasattr(bin_base_name, 'removesuffix'):
            _bin_name = bin_base_name.removesuffix('.zip')
        else:
            # python < 3.9 does not support removesuffix
            _bin_name = bin_base_name[:-4] if bin_base_name.endswith('.zip') else bin_base_name
        new_bin_path = os.path.join(_tmp_dir(), f'{bin_hash}', _bin_name)
        os.makedirs(new_bin_path, exist_ok=True)
        with zipfile.ZipFile(bin_path, 'r') as zip_ref:
            zip_ref.extractall(new_bin_path)
        bin_path = new_bin_path
    if 'partition_table' not in os.listdir(bin_path):
        logger.warning('Can not find partition_table from bin_path, maybe invalid!')
    return bin_path


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


def _parse_partition_table_to_csv(parttool_path: str, part_bin: str, part_csv: str) -> str:
    logger.debug(f'Generating partition-table.csv to {part_csv}')
    try:
        _cmd = ['python', parttool_path, str(part_bin), str(part_csv)]
        subprocess.check_call(_cmd, shell=False)
        # make sure partition-table.csv is generated
        for _ in range(20):
            if Path(part_csv).is_file():
                break
            time.sleep(0.05)
        else:
            raise FileNotFoundError(f'{part_csv} is not created after 1 second')
    except subprocess.SubprocessError as e:
        logger.error(f'Failed to gen {part_csv}: {str(e)}')
        raise e
    return part_csv


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
                        key = key.strip()
                        if hasattr(key, 'removeprefix'):
                            key = key.removeprefix('CONFIG_')
                        else:
                            # python < 3.9 does not support removeprefix
                            if key.startswith('CONFIG_'):
                                key = key[7:]
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
                        config_name = line.strip()
                        if hasattr(config_name, 'removeprefix'):
                            config_name = config_name.removeprefix('# CONFIG_').removesuffix(' is not set')
                        else:
                            # python < 3.9 does not support removeprefix
                            config_name = config_name[9:] if config_name.startswith('# CONFIG_') else config_name
                            config_name = config_name[:-11] if config_name.endswith(' is not set') else config_name
                        sdkconfig[config_name] = False
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

    @property
    def secure_boot_config(self) -> bool:
        """Get secure boot status from SDK config"""
        assert self, 'SDKConfig is not initialized'
        if 'SECURE_BOOT' not in self:
            logger.warning('SECURE_BOOT not found in sdkconfig')
        return bool(self.get('SECURE_BOOT', False))


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
        if not os.path.isdir(self.bin_path):
            self.bin_path = bin_path_to_dir(self.bin_path)
        self._parttool = parttool
        self._flasher_args: t.Dict[str, t.Any] = {}
        self._sdkconfig: SDKConfig = SDKConfig()
        self._partition_table_csv_path: str = ''  # set when partition_table dir is read-only

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
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f'parse flasher_args.json failed: {flasher_args_file}, {type(e)}: {str(e)}')
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

    def _rev_range_from_bootloader(self, chip_name: str) -> t.Tuple[int, int]:
        """Read (min_rev_full, max_rev_full) from package bootloader.bin.

        Requires esptool >= 4.3 (``min_rev_full`` / ``max_rev_full`` were added
        then). Older esptool only exposes legacy ``min_rev`` and will raise
        AttributeError here.
        """
        from esptool.bin_image import LoadFirmwareImage

        if not chip_name or chip_name == 'auto':
            raise ValueError(f'chip must be a concrete target, got {chip_name!r}')
        boot_rel = self.flasher_args['bootloader']['file']
        boot_path = os.path.join(self.bin_path, boot_rel)
        image = LoadFirmwareImage(chip_name, boot_path)
        return int(image.min_rev_full), int(image.max_rev_full)

    def _rev_range_from_sdkconfig(self) -> t.Tuple[int, int]:
        """Read (min_rev_full, max_rev_full) from sdkconfig FULL keys."""
        cfg = self.sdkconfig
        if 'ESP_REV_MIN_FULL' in cfg and 'ESP_REV_MAX_FULL' in cfg:
            return int(cfg['ESP_REV_MIN_FULL']), int(cfg['ESP_REV_MAX_FULL'])

        # Target-prefixed pairs, e.g. ESP32C5_REV_MIN_FULL / ESP32C5_REV_MAX_FULL
        min_keys = [
            k for k in cfg if k.endswith('_REV_MIN_FULL') and 'EFUSE_BLOCK' not in k and k != 'ESP_REV_MIN_FULL'
        ]
        for min_key in sorted(min_keys):
            prefix = min_key[: -len('_REV_MIN_FULL')]
            max_key = prefix + '_REV_MAX_FULL'
            if max_key in cfg:
                return int(cfg[min_key]), int(cfg[max_key])
        raise ValueError('sdkconfig missing *_REV_MIN_FULL / *_REV_MAX_FULL pair')

    def get_supported_chip_rev_range(
        self,
        chip: t.Optional[str] = None,
    ) -> t.Tuple[int, int]:
        """Return (min_rev_full, max_rev_full) supported by this firmware package.

        Prefer bootloader image headers; fall back to sdkconfig ``*_REV_*_FULL``
        keys. Raise ValueError if both sources fail.

        Bootloader path needs esptool >= 4.3 for ``min_rev_full`` /
        ``max_rev_full``. On older esptool the bootloader read fails and this
        method falls back to sdkconfig.

        Older IDF builds that never set chip revision limits may return
        ``(0, 0)``, which means min/max were not configured (not a parse
        failure).
        """
        chip_name = self.chip if chip is None else chip
        boot_err: t.Optional[BaseException] = None
        try:
            return self._rev_range_from_bootloader(chip_name)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            boot_err = exc
            logger.warning(
                'failed to read bootloader rev range from %s: %s',
                self.bin_path,
                exc,
            )

        sdk_err: t.Optional[BaseException] = None
        try:
            return self._rev_range_from_sdkconfig()
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            sdk_err = exc

        raise ValueError(
            f'failed to get supported chip rev range from bootloader ({boot_err}) and sdkconfig ({sdk_err})'
        )

    @property
    def partition_table_csv_path(self) -> Path:
        """Get partition-table.csv path"""
        if self._partition_table_csv_path:
            return Path(self._partition_table_csv_path)
        return Path(self.bin_path) / 'partition_table' / 'partition-table.csv'

    @lru_cache()
    def _gen_partition_table(self, part_csv: t.Optional[Path] = None) -> None:
        part_csv = Path(self.bin_path) / 'partition_table' / 'partition-table.csv'
        part_bin = Path(self.bin_path) / 'partition_table' / 'partition-table.bin'
        if part_csv.is_file():
            # already exists
            return
        if not self.parttool_path or not part_bin.is_file():
            logger.error('Can not gen partition-table.csv: parttool_path or partition-table.bin not found')
            return
        if not os.access(part_csv.parent, os.W_OK):
            # partition_table dir is read-only, use tmp dir for .csv
            part_csv = Path(tempfile.mktemp(suffix='.csv'))
            self._partition_table_csv_path = str(part_csv)
        logger.debug(f'Generating partition-table.csv to {part_csv}')
        _parse_partition_table_to_csv(self.parttool_path, str(part_bin), str(part_csv))

    def _parse_partition_table_csv(self, partition_table_file: Path) -> t.List[PartitionInfo]:
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

    def parse_partitions(self) -> t.List[PartitionInfo]:
        """Parse partitions from partition-table.csv"""
        self._gen_partition_table()
        partition_table_file = self.partition_table_csv_path
        if not partition_table_file.is_file():
            raise ValueError('Can not parse partition table')
        return self._parse_partition_table_csv(partition_table_file)

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
        nvs_partition_info = self.get_partition_info('nvs')
        nvs_bin = tempfile.mktemp()
        with open(nvs_bin, 'wb+') as f:
            f.write(b'\xff' * nvs_partition_info.size)
        return nvs_partition_info.offset, nvs_bin

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

    def _check_secure_boot_match(self, secure_boot: bool) -> None:
        if secure_boot != self.sdkconfig.secure_boot_config:
            msg = (
                f'Secure Boot status mismatch! '
                f'SDKConfig.secure_boot={self.sdkconfig.secure_boot_config}, '
                f'efuse secure_boot_enabled={secure_boot}. '
                f'Refusing to flash bin.'
            )
            raise RuntimeError(msg)

    def flash_bin_args(
        self,
        baudrate: int = 0,
        erase_nvs: bool = True,
        encrypted: bool = False,
        secure_boot: bool = False,
    ) -> t.List[str]:
        """Get write_flash args / command for esptool.

        Args:
            baudrate (int, optional): baudrate for flashing.
            erase_nvs (bool, optional): whether to erase nvs partition.
            encrypted (bool, optional): whether to flash with encryption.
            secure_boot (bool, optional): whether to flash with secure boot.
        """
        args = self._write_flash_args_common(baudrate)
        if encrypted:
            args += ['--encrypt']
        if secure_boot:
            # Secure Boot blocks writes to protected regions without --force
            # Can't use idf.py flash, can use python -m esptool command in build_log
            args += ['--force']
        # always check secure boot match because efuse will be auto-flashed before idf v6.1 if secure boot is enabled
        self._check_secure_boot_match(secure_boot)
        for offset, bin_file in self.flasher_args['flash_files'].items():
            args += [offset, str(Path(self.bin_path) / bin_file)]
        if erase_nvs:
            args += list(self._gen_erase_nvs_bin())
        return args

    def flash_nvs_args(self, nvs_bin: str = '') -> t.List[str]:
        args = self._write_flash_args_common()
        # write nvs
        nvs_partition_info = self.get_partition_info('nvs')
        if nvs_bin:
            return args + [nvs_partition_info.offset, nvs_bin]
        # erase nvs
        return args + list(self._gen_erase_nvs_bin())

    def dump_nvs_args(self, filename: str) -> t.List[str]:
        args = [
            '--chip',
            self.chip,
            '--before',
            self.flasher_args['extra_esptool_args']['before'],
            '--after',
            'hard_reset',
        ]
        if not self.stub:
            args += ['--no-stub']
        nvs_partition_info = self.get_partition_info('nvs')
        args += ['read_flash', nvs_partition_info.offset, str(nvs_partition_info.size), str(filename)]
        return args

    def flash_partition_args(self, partition_bins: t.Dict[str, str]) -> t.List[str]:
        """Get write_flash args for a partition"""
        args = self._write_flash_args_common()
        for partition_name, partition_bin in partition_bins.items():
            part = self.get_partition_info(partition_name)
            partition_offset = part.offset
            if not partition_bin and partition_name == 'nvs':
                logger.warning(f'No partition {partition_name} bin file provided, generating a empty one for erasing')
                partition_bin = tempfile.mktemp()
                with open(partition_bin, 'wb+') as f:
                    f.write(b'\xff' * part.size)
            if not partition_bin or not Path(partition_bin).is_file():
                raise ValueError(f'Can not find or open partition bin file: {partition_bin}')
            args += [partition_offset, partition_bin]
        return args

    def get_partition_info(self, part_name: str) -> PartitionInfo:
        for part in self.parse_partitions():
            if part.name == part_name:
                return part
        raise ValueError(f'Can not find {part_name} partition info')
