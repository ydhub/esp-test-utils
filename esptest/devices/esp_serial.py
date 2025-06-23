from dataclasses import dataclass
from functools import lru_cache

import esptool
from packaging.version import Version
from serial.tools.list_ports_common import ListPortInfo

import esptest.common.compat_typing as t

from ..common.decorators import suppress_stdout
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
    chip_version: str = ''
    mac: str = ''
    target: str = 'unknown'


def _chip_name_to_target(name: str) -> str:
    # c61 must after c6
    for suffix in ['s2', 's3', 's5', 's6', 'c2', 'c3', 'c5', 'c61', 'c6', 'p4', 'h2', 'h4']:
        if name == f'ESP32-{suffix.upper()}':
            return f'esp32{suffix}'
    if name == 'ESP32':
        return 'esp32'
    return 'unknown'


def _get_esp_port_info(esp: esptool.ESPLoader) -> dict[str, t.Any]:
    _info = {}
    try:
        _info['chip_name'] = esp.CHIP_NAME
        _info['mac'] = ':'.join([f'{i:02x}' for i in esp.read_mac()])
        _info['chip_description'] = esp.get_chip_description()
        _info['chip_version'] = f'v{esp.get_major_chip_version()}.{esp.get_minor_chip_version()}'
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f'Get esp port info failed {type(e)}: {str(e)}')
        # do not update _info
    _info['target'] = _chip_name_to_target(_info['chip_name'])
    return _info


@lru_cache
@suppress_stdout()
def detect_one_port(port: ListPortInfo) -> EspPortInfo:
    if not port:
        raise ValueError('detect port "port" not be given')
    _device = port.device
    _location = port.location or ''
    _info = {'serial_description': port.description or ''}
    _support_esptool = True
    try:
        if Version(esptool.__version__) > Version('4.8.dev3'):
            # Newer esptool supports context manager
            with esptool.detect_chip(_device) as esp:
                _info = _get_esp_port_info(esp)
                esp.hard_reset()
        else:
            # old esptool <= 4.7
            esp = esptool.detect_chip(_device)
            _info = _get_esp_port_info(esp)
            esp.hard_reset()
            esp._port.close()  # pylint: disable=protected-access
        logger.info(f'Auto-Detect chip {_device}: {_info}')
    except esptool.util.FatalError:
        logger.warning(f'Detect {port} does not support esptool, may not be an esp port!')
        _support_esptool = False
    return EspPortInfo(_device, _location, _support_esptool, **_info)


def list_all_esp_ports() -> t.List[EspPortInfo]:
    esp_ports = []
    for port in get_all_serial_ports():
        esp_ports.append(detect_one_port(port))
    return esp_ports
