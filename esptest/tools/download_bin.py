import asyncio
import concurrent
import concurrent.futures
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from asyncio.events import AbstractEventLoop
from functools import lru_cache, partial

from esptool import get_default_connected_device

import esptest.common.compat_typing as t
from esptest.devices.serial_tools import compute_serial_port
from esptest.logger import get_logger
from esptest.tools.http_download import download_file
from esptest.utility.parse_bin_path import ParseBinPath

logger = get_logger('download_bin')


@lru_cache()
def _get_bin_parser(bin_path: str, parttool: str) -> ParseBinPath:
    return ParseBinPath(bin_path, parttool)


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
        if hasattr(bin_base_name, 'removeprefix'):
            _bin_name = bin_base_name.removeprefix('.zip')
        else:
            # python < 3.9 does not support removeprefix
            _bin_name = bin_base_name[:-4] if bin_base_name.endswith('.zip') else bin_base_name
        new_bin_path = os.path.join(_tmp_dir(), f'{bin_hash}', _bin_name)
        os.makedirs(new_bin_path, exist_ok=True)
        with zipfile.ZipFile(bin_path, 'r') as zip_ref:
            zip_ref.extractall(new_bin_path)
        bin_path = new_bin_path
    if 'partition_table' not in os.listdir(bin_path):
        logger.warning('Can not find partition_table from bin_path, maybe invalid!')
    return bin_path


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


class DownBinTool:
    # RETRY_CNT = 2
    DEFAULT_BAUD_LIST = [921600, 460800]
    FLASH_CRYPT_CNT_PATTERN = re.compile(r'(?:FLASH_CRYPT_CNT|SPI_BOOT_CRYPT_CNT).*\(0b([01]+)')

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

    def check_flash_encrypted(self, efuse_summary: str) -> bool:
        match = self.FLASH_CRYPT_CNT_PATTERN.search(efuse_summary)
        if match:
            return match.group(1).count('1') % 2 == 1
        return False

    def download(self) -> None:
        efuse_cmd = self.espefuse.split()
        try:
            summary = subprocess.check_output(
                efuse_cmd + ['--port', self.port, 'summary'], stderr=subprocess.STDOUT, text=True
            )
        except subprocess.CalledProcessError as err:
            logger.error(err.output)
            raise RuntimeError(f'Failed to get efuse information from {self.port}') from err

        enc_indicator = ' [encrypted]' if self.check_flash_encrypted(summary) else ''

        download_log = ''
        for baud in self.baud_list:
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
                    args += ['--no-stub'] if '--no-stub' not in args else []
            args += ['-p', self.port]
            args += ['-b', f'{baud}']
            args += self.bin_parser.flash_bin_args(erase_nvs=self.erase_nvs, encrypted=bool(enc_indicator))

            logger.info(f'Downloading {self.port}@{baud}{enc_indicator}: {self.bin_path}')
            logger.debug(f'esptool cmd: {" ".join(args)}')
            # get return code rather than check
            ret = subprocess.run(args, capture_output=True, text=True, check=False)
            if ret.returncode == 0:
                return  # succeed
            # failed
            download_log += f'esptool cmd failed ({ret.returncode}): ' + ' '.join(args)
            download_log += f'\nDownload failed: [{self.port}@{baud}]\n'
            esptool_msg = ret.stdout + ret.stderr
            download_log += f'esptool output: {_filter_esptool_log(esptool_msg)}'
        logger.error(download_log)
        raise RuntimeError(f'Failed to download Bin to {self.port}')


def _download_bin(down_tool: DownBinTool) -> None:
    down_tool.download()


async def _async_download_bin(down_tool: DownBinTool, loop: AbstractEventLoop) -> None:
    async_func = partial(_download_bin, down_tool)
    await loop.run_in_executor(None, async_func)


async def async_download_bin_scheduler(  # pylint: disable=too-many-positional-arguments
    bin_path: str,
    ports: t.List[str],
    erase_nvs: bool = True,
    max_workers: int = 0,
    force_no_stub: bool = False,
    check_no_stub: bool = False,
) -> None:
    max_workers = max_workers or len(ports)
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=max_workers))

    coroutines = []
    for _port in ports:
        down_tool = DownBinTool(
            bin_path, _port, erase_nvs=erase_nvs, force_no_stub=force_no_stub, check_no_stub=check_no_stub
        )
        coroutines.append(_async_download_bin(down_tool, loop))

    await asyncio.gather(*coroutines)


def download_bin_to_ports(  # pylint: disable=too-many-positional-arguments
    bin_path: str,
    ports: t.List[str],
    erase_nvs: bool = True,
    max_workers: int = 0,
    force_no_stub: bool = False,
    check_no_stub: bool = False,
) -> None:
    asyncio.run(async_download_bin_scheduler(bin_path, ports, erase_nvs, max_workers, force_no_stub, check_no_stub))
