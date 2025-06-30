import asyncio
import concurrent
import concurrent.futures
import subprocess
from asyncio.events import AbstractEventLoop
from functools import lru_cache, partial

import esptest.common.compat_typing as t
from esptest.devices.serial_tools import compute_serial_port
from esptest.logger import get_logger
from esptest.utility.parse_bin_path import ParseBinPath

logger = get_logger('download_bin')


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
    ):  # pylint: disable=too-many-positional-arguments,too-many-arguments
        self.bin_path = bin_path
        self.port = compute_serial_port(port, strict=True)
        if isinstance(baud, int):
            self.baud_list = [baud] if baud > 0 else self.DEFAULT_BAUD_LIST
        else:
            self.baud_list = baud
        self.esptool = esptool or 'python -m esptool'
        self.erase_nvs = erase_nvs
        self.bin_parser = _get_bin_parser(bin_path, parttool)

    def download(self) -> None:
        download_log = ''
        for baud in self.baud_list:
            args = self.esptool.split()
            args += ['-p', self.port]
            args += ['-b', f'{baud}']
            args += self.bin_parser.flash_bin_args(erase_nvs=self.erase_nvs)

            logger.critical(f'Downloading {self.port}@{baud}: {self.bin_path}')
            # get return code rather than check
            ret = subprocess.run(args, capture_output=True, text=True, check=False)
            if ret.returncode == 0:
                return  # succeed
            # failed
            download_log = f'esptool cmd failed ({ret.returncode}): ' + ' '.join(args)
            download_log += f'\nDownload failed: [{self.port}@{baud}]\n'
            esptool_msg = ret.stdout + ret.stderr
            download_log += f'esptool output: {_filter_esptool_log(esptool_msg)}'
            logger.debug(download_log)
        logger.error(download_log)
        raise RuntimeError(f'Failed to download Bin to {self.port}')


def _download_bin(down_tool: DownBinTool) -> None:
    down_tool.download()


async def _async_download_bin(down_tool: DownBinTool, loop: AbstractEventLoop) -> None:
    async_func = partial(_download_bin, down_tool)
    await loop.run_in_executor(None, async_func)


async def async_download_bin_scheduler(
    bin_path: str,
    ports: t.List[str],
    erase_nvs: bool = True,
    max_workers: int = 0,
) -> None:
    max_workers = max_workers or len(ports)
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=max_workers))

    coroutines = []
    for _port in ports:
        down_tool = DownBinTool(bin_path, _port, erase_nvs=erase_nvs)
        coroutines.append(_async_download_bin(down_tool, loop))

    await asyncio.gather(*coroutines)


def download_bin_to_ports(bin_path: str, ports: t.List[str], erase_nvs: bool = True, max_workers: int = 0) -> None:
    asyncio.run(async_download_bin_scheduler(bin_path, ports, erase_nvs, max_workers))
