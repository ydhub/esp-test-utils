import asyncio
import concurrent
import concurrent.futures
import re
import subprocess
import sys
from asyncio.events import AbstractEventLoop
from dataclasses import dataclass
from functools import lru_cache, partial

from esptool import get_default_connected_device

import esptest.common.compat_typing as t
from esptest.devices.serial_tools import compute_serial_port
from esptest.logger import get_logger
from esptest.utility.parse_bin_path import (  # pylint: disable=unused-import
    ParseBinPath,
    bin_path_to_dir,  # noqa: F401
)

logger = get_logger('download_bin')
FLASH_CRYPT_CNT_PATTERN = re.compile(r'(?:FLASH_CRYPT_CNT|SPI_BOOT_CRYPT_CNT).*\(0b([01]+)')
SECURE_BOOT_EN_PATTERN = re.compile(r'(?:ABS_DONE_1|SECURE_BOOT_EN).*?\((0b[01]+)\)')


@lru_cache()
def _get_bin_parser(bin_path: str, parttool: str) -> ParseBinPath:
    return ParseBinPath(bin_path, parttool)


def _filter_esptool_log(log: str) -> str:
    lines = log.splitlines(keepends=True)
    new_log = ''
    last_line = ''
    for _, line in enumerate(lines):
        if not line.startswith('Writing at'):
            if last_line.startswith('Writing at'):
                new_log += last_line
            new_log += line
        elif not last_line.startswith('Writing at'):
            new_log += line
        last_line = line
    return new_log


def check_flash_encrypted(efuse_summary: str) -> bool:
    """Check whether flash encryption is enabled from efuse summary."""
    match = FLASH_CRYPT_CNT_PATTERN.search(efuse_summary)
    if match:
        return match.group(1).count('1') % 2 == 1
    return False


def check_secure_boot_enabled(efuse_summary: str) -> bool:
    """Check whether secure boot is enabled from efuse summary."""
    match = SECURE_BOOT_EN_PATTERN.search(efuse_summary)
    if match:
        return match.group(1) == '0b1'
    return False


class DownBinTool:
    # RETRY_CNT = 2
    DEFAULT_BAUD_LIST = [921600, 460800]

    def __init__(
        self,
        bin_path: str,
        port: str,
        baud: t.Union[int, t.List[int]] = -1,
        parttool: str = '',
        esptool: str = '',
        erase_nvs: bool = True,
        force_no_stub: bool = False,
        check_no_stub: bool = False,
    ):  # pylint: disable=too-many-positional-arguments,too-many-arguments
        self.bin_path = bin_path
        self.port = compute_serial_port(port, strict=True)
        if isinstance(baud, int):
            self.baud_list = [baud] if baud > 0 else self.DEFAULT_BAUD_LIST
        else:
            self.baud_list = baud
        self.esptool = esptool or f'{sys.executable} -m esptool'
        self.espefuse = self.esptool.replace('esptool', 'espefuse')
        self.erase_nvs = erase_nvs
        self.bin_parser = _get_bin_parser(bin_path, parttool)
        self.force_no_stub = force_no_stub
        self.check_no_stub = check_no_stub

    @property
    def _base_esptool_args(self) -> t.List[str]:
        args = self.esptool.split()
        if self.force_no_stub:
            args += ['--no-stub'] if '--no-stub' not in args else []
        elif self.check_no_stub:
            esp = get_default_connected_device(
                [self.port],
                port=self.port,
                connect_attempts=3,
                initial_baud=self.baud_list[0],
                chip='auto',
            )
            if not esp.IS_STUB:  # type: ignore
                logger.debug(f'Add --no-stub for device: {self.port}')
                args += ['--no-stub'] if '--no-stub' not in args else []
        args += ['-p', self.port]
        return args

    def download(self) -> None:
        efuse_cmd = self.espefuse.split()
        try:
            summary = subprocess.check_output(
                efuse_cmd + ['--port', self.port, 'summary'], stderr=subprocess.STDOUT, text=True
            )
        except subprocess.CalledProcessError as err:
            logger.error(err.output)
            raise RuntimeError(f'Failed to get efuse information from {self.port}') from err
        encrypted_indicator = ' [encrypted]' if check_flash_encrypted(summary) else ''
        secure_boot_indicator = ' [secure_boot]' if check_secure_boot_enabled(summary) else ''

        download_log = ''
        for baud in self.baud_list:
            args = self._base_esptool_args
            args += ['-b', f'{baud}']
            args += self.bin_parser.flash_bin_args(
                erase_nvs=self.erase_nvs, encrypted=bool(encrypted_indicator), secure_boot=bool(secure_boot_indicator)
            )

            logger.info(f'Downloading {self.port}@{baud}{encrypted_indicator}{secure_boot_indicator}: {self.bin_path}')
            logger.debug(f'esptool cmd: {" ".join(args)}')
            # get return code rather than check
            ret = subprocess.run(args, capture_output=True, text=True, check=False)
            if ret.returncode == 0:
                logger.info(f'Download success: [{self.port}@{baud}]')
                return  # succeed
            # failed
            download_log += f'esptool cmd failed ({ret.returncode}): ' + ' '.join(args)
            download_log += f'\nDownload failed: [{self.port}@{baud}]\n'
            esptool_msg = ret.stdout + ret.stderr
            download_log += f'esptool output: {_filter_esptool_log(esptool_msg)}'
        logger.error(download_log)
        raise RuntimeError(f'Failed to download Bin to {self.port}')

    def download_partition(self, partition_bins: t.Dict[str, str]) -> None:
        """
        Download partitions from bin file to device, use slower baud rate without retry.

        Args:
            partition_bins (t.Dict[str, str]): A dictionary of partition name and partition bin file path.
        """
        args = self._base_esptool_args
        baud = self.baud_list[-1]
        args += ['-b', f'{baud}']
        args += self.bin_parser.flash_partition_args(partition_bins)
        ret = subprocess.run(args, capture_output=True, text=True, check=False)
        if ret.returncode == 0:
            logger.info(f'Download success: [{self.port}@{baud}]')
            return  # succeed
        # failed
        download_log = ''
        download_log += f'esptool cmd failed ({ret.returncode}): ' + ' '.join(args)
        download_log += f'\nDownload failed: [{self.port}@{baud}]\n'
        esptool_msg = ret.stdout + ret.stderr
        download_log += f'esptool output: {_filter_esptool_log(esptool_msg)}'
        logger.error(download_log)
        raise RuntimeError(f'Failed to download partitions {list(partition_bins.keys())} to {self.port}')


def _download_bin(down_tool: DownBinTool) -> None:
    down_tool.download()


async def _async_download_bin(down_tool: DownBinTool, loop: AbstractEventLoop) -> None:
    async_func = partial(_download_bin, down_tool)
    await loop.run_in_executor(None, async_func)


async def async_download_bin_scheduler(  # pylint: disable=too-many-positional-arguments,too-many-arguments
    bin_path: str,
    ports: t.List[str],
    erase_nvs: bool = True,
    max_workers: int = 0,
    force_no_stub: bool = False,
    check_no_stub: bool = False,
    baud: t.Union[int, t.List[int]] = 0,
    esptool: str = '',
) -> None:
    max_workers = max_workers or len(ports)
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=max_workers))

    coroutines = []
    for _port in ports:
        down_tool = DownBinTool(
            bin_path,
            _port,
            baud=baud,
            erase_nvs=erase_nvs,
            esptool=esptool,
            force_no_stub=force_no_stub,
            check_no_stub=check_no_stub,
        )
        coroutines.append(_async_download_bin(down_tool, loop))

    await asyncio.gather(*coroutines)


def download_bin_to_ports(  # pylint: disable=too-many-positional-arguments,too-many-arguments
    bin_path: str,
    ports: t.List[str],
    erase_nvs: bool = True,
    max_workers: int = 0,
    force_no_stub: bool = False,
    check_no_stub: bool = False,
    baud: t.Union[int, t.List[int]] = 0,
    esptool: str = '',
) -> None:
    """
    Download bin to ports using esptool.

    Args:
        bin_path: Path to the bin file.
        ports: List of serial ports.
        erase_nvs: Whether to erase nvs before flashing.
        max_workers: Maximum number of workers to use.
        force_no_stub: Whether to force no stub.
        check_no_stub: Whether to check no stub.
        baud: Baud rate to use. If given a list, will try each baud rate in order.
        esptool: Path to the esptool executable.
    """
    asyncio.run(
        async_download_bin_scheduler(
            bin_path, ports, erase_nvs, max_workers, force_no_stub, check_no_stub, baud, esptool
        )
    )


@dataclass
class BinConfig:
    """
    Configuration for downloading a bin to a port.

    Args:
        bin_path: Path to the bin file.
        port: Serial port to download to.
        erase_nvs: Whether to erase nvs before flashing.
        force_no_stub: Whether to force no stub.
        check_no_stub: Whether to check no stub.
        baud: Baud rate to use. If given a list, will try each baud rate in order.
        esptool: Path to the esptool executable.
    """

    bin_path: str
    port: str
    erase_nvs: bool = True
    force_no_stub: bool = False
    check_no_stub: bool = False
    baud: t.Union[int, t.List[int]] = 0
    esptool: str = ''


async def async_downbin_scheduler(
    bin_configs: t.List[BinConfig],
    max_workers: int = 0,
) -> None:
    max_workers = max_workers or len(bin_configs)
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=max_workers))

    coroutines = []
    for cfg in bin_configs:
        down_tool = DownBinTool(
            cfg.bin_path,
            cfg.port,
            baud=cfg.baud,
            erase_nvs=cfg.erase_nvs,
            esptool=cfg.esptool,
            force_no_stub=cfg.force_no_stub,
            check_no_stub=cfg.check_no_stub,
        )
        coroutines.append(_async_download_bin(down_tool, loop))

    await asyncio.gather(*coroutines)


def download_bins(bin_configs: t.List[BinConfig], max_workers: int = 0) -> None:
    """
    Download bins to ports using esptool.

    Args:
        bin_configs: List of configuration for downloading a bin to a port.
        max_workers: Maximum number of workers to use.
    """
    asyncio.run(async_downbin_scheduler(bin_configs, max_workers))
