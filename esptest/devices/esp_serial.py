import contextlib
from dataclasses import dataclass
from functools import lru_cache

import esptool
import serial
from packaging.version import Version
from serial.tools.list_ports_common import ListPortInfo

import esptest.common.compat_typing as t

from ..common.decorators import suppress_stdout
from ..config.global_config import g
from ..logger import get_logger
from .serial_tools import get_all_serial_ports

logger = get_logger('esp_serial')


@dataclass
class EspPortInfo:
    device: str
    location: str
    support_esptool: bool
    serial_description: str = ''
    chip_name: str = ''
    chip_description: str = ''
    mac: str = ''
    chip_version: str = ''
    # major*100+minor; same scale as bootloader min_rev_full / max_rev_full.
    # -1 means unknown / not read.
    chip_rev_full: int = -1
    chip_xtal: str = ''
    flash_id: str = ''
    flash_size: str = ''
    # pid: int = 0
    # vid: int = 0
    target: str = 'unknown'


def _chip_name_to_target(name: str) -> str:
    # c61 must after c6
    for suffix in ['s2', 's3', 's5', 's6', 'c2', 'c3', 'c5', 'c61', 'c6', 'p4', 'h2', 'h4']:
        if name == f'ESP32-{suffix.upper()}':
            return f'esp32{suffix}'
    if name == 'ESP32':
        return 'esp32'
    return 'unknown'


def _get_esp_port_info(esp: esptool.ESPLoader) -> t.Dict[str, t.Any]:
    _info = {}
    _info['chip_name'] = esp.CHIP_NAME
    try:
        _info['mac'] = ':'.join([f'{i:02x}' for i in esp.read_mac()])
        _info['chip_description'] = esp.get_chip_description()
        major = int(esp.get_major_chip_version())
        minor = int(esp.get_minor_chip_version())
        _info['chip_version'] = f'v{major}.{minor}'
        _info['chip_rev_full'] = major * 100 + minor
        _info['chip_xtal'] = f'{esp.get_crystal_freq()}'
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f'[{esp.port}] Get esp port info failed {type(e)}: {str(e)}')
        # do not update _info
    try:
        from esptool.cmds import attach_flash, detect_flash_size

        # ROM loader does not enable SPI flash until attach_flash() is called.
        attach_flash(esp)
        _info['flash_id'] = hex(esp.flash_id())
        _info['flash_size'] = detect_flash_size(esp)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f'[{esp.port}] Detect flash info failed {type(e)}: {str(e)}')
        # ignore update _info
    _info['target'] = _chip_name_to_target(_info['chip_name'])
    return _info


@contextlib.contextmanager
def esptool_detect_chip(port: str, **kwargs: t.Any) -> t.Generator[esptool.ESPLoader, None, None]:
    """Detect chip on ``port`` with esptool 4.7 / 4.8+ cleanup compatibility.

    Extra keyword arguments are forwarded to ``esptool.detect_chip``
    (e.g. ``baud`` / ``baudrate``, ``connect_attempts``, ``connect_mode``,
    ``trace_enabled``). ``baudrate`` is accepted as an alias of ``baud``.

    esptool >= 4.8 provides ``ESPLoader`` context-manager support; older 4.7
    releases require closing ``esp._port`` manually.
    """
    if 'baudrate' in kwargs:
        if 'baud' not in kwargs:
            kwargs['baud'] = kwargs.pop('baudrate')
        else:
            kwargs.pop('baudrate')
    if Version(esptool.__version__) > Version('4.8.dev3'):
        with esptool.detect_chip(port, **kwargs) as esp:
            yield esp
    else:
        esp = esptool.detect_chip(port, **kwargs)
        try:
            yield esp
        finally:
            esp._port.close()  # pylint: disable=protected-access


@suppress_stdout()
def detect_port_info_no_cache(device: str, location: str = '', description: str = '') -> EspPortInfo:
    _info = {}
    _support_esptool = True
    try:
        with esptool_detect_chip(device) as esp:
            _info = _get_esp_port_info(esp)
            esp.hard_reset()
        _info['serial_description'] = description or ''
        logger.info(f'Auto-Detect chip {device}: {_info}')
    except (esptool.util.FatalError, serial.SerialException) as e:
        # SerialTimeoutException (subclass of SerialException) can happen on
        # non-UART bridges or busy ports; must not abort list_all_esp_ports.
        logger.warning(f'Detect {device} via esptool failed {type(e)}: {str(e)}')
        _info['serial_description'] = description or ''
        _info['chip_description'] = f'esptool {type(e)}: {str(e)}'
        _support_esptool = False
    return EspPortInfo(device, location, _support_esptool, **_info)


def _should_skip_esptool_detect(port: ListPortInfo) -> bool:
    vid = getattr(port, 'vid', None)
    pid = getattr(port, 'pid', None)
    if vid is None or pid is None:
        return False
    return (vid, pid) in g.SKIP_ESPTOOL_DETECT_VID_PID


@lru_cache()  # bare @lru_cache is not supported on Python 3.7
def detect_one_port(port: ListPortInfo) -> EspPortInfo:
    if _should_skip_esptool_detect(port):
        logger.info(f'Skip esptool detect on {port.device} (vid={port.vid:04x} pid={port.pid:04x}): {port.description}')
        return EspPortInfo(
            port.device,
            port.location or '',
            False,
            serial_description=port.description or '',
            chip_description=f'skip detect vid={port.vid:04x} pid={port.pid:04x}',
        )
    return detect_port_info_no_cache(port.device, port.location, port.description)


def list_all_esp_ports() -> t.List[EspPortInfo]:
    esp_ports = []
    for port in get_all_serial_ports():
        esp_ports.append(detect_one_port(port))
    return esp_ports


def get_available_ports(target: str, max_num: int = 0) -> t.List[EspPortInfo]:
    detect_ports = []
    for port in get_all_serial_ports():
        esp_port = detect_one_port(port)
        if esp_port.target == target:
            detect_ports.append(esp_port)
        if max_num > 0 and len(detect_ports) >= max_num:  # pylint: disable=chained-comparison
            return detect_ports
    return detect_ports
