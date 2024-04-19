import codecs
import re
import time
from typing import Optional

import serial
from serial.tools.list_ports_common import ListPortInfo

from ..logger import get_logger
from .serial_tools import get_all_serial_ports

logger = get_logger('devices')


def set_att(port: ListPortInfo, att: int, att_fix: bool = False) -> bool:
    """set attenuation value on the attenuator

    :param str port: serial port for attenuator
    :param int att: attenuation value we want to set
    :param bool att_fix: fix the deviation with experience value, defaults to False
    """
    result = False
    serial_port = serial.Serial(port.device, baudrate=9600, rtscts=False, timeout=0.1)
    if not serial_port.is_open:
        raise IOError('attenuator control, failed to open att port')
    if port.vid in (0x067B, 0x0403):
        assert 0 <= att <= 62
        # fix att
        if att_fix:
            if att >= 33 and (att - 30 + 1) % 4 == 0:
                att_t = att - 1
            elif att >= 33 and (att - 30) % 4 == 0:
                att_t = att + 1
            else:
                att_t = att
        else:
            att_t = att
        cmd_hex = f'7e7e10{att_t:02x}{0x10+att_t:x}'
        exp_res_hex = f'7e7e20{att_t:02x}00{0x20+att_t:x}'

        cmd = codecs.decode(cmd_hex, 'hex')
        exp_res = codecs.decode(exp_res_hex, 'hex')
        serial_port.write(cmd)
        _raw_bytes = b''
        for _ in range(5):
            _raw_bytes += serial_port.read(20)
            if _raw_bytes == exp_res:
                result = True
                break
            time.sleep(0.1)
    elif port.vid == 0x0483:
        assert 0 <= att <= 92
        serial_port.write(f'att-{att:03d}.00\r\n'.encode())
        time.sleep(0.5)
        assert b'attOK' in serial_port.read(20)
        serial_port.write(b'READ\r\n')
        time.sleep(0.5)
        _raw_data = serial_port.read(200).decode('utf-8', errors='ignore')
        match = re.match(re.compile(r'ATT = -(\d+).00'), _raw_data)
        assert match and int(match.group(1)) == att, 'Set att fail!'
        result = True
    serial_port.close()
    return result


def find_att_port(port: Optional[str] = None) -> ListPortInfo:
    """Find or detect a att port

    Args:
        port (Optional[str], optional): port name/device/location. Defaults to None (auto-detect).

    Returns:
        ListPortInfo: port info object, including attributes devices, pid, vid, etc.
    """

    att_port = None
    p_list = get_all_serial_ports()
    if port:
        for p_info in p_list:
            if port in (p_info.device, p_info.name, p_info.location):
                att_port = p_info
                break
    else:
        # auto detect
        logger.info('ATT port not given, searching for an available port.')
        for p_info in p_list:
            if p_info.vid == 0x0483 and p_info.pid == 0x5740:
                # wuyou electronics(Dc-6ghz 90db)
                att_port = p_info
                break
            if p_info.vid == 0x067B and p_info.pid == 0x2303:
                # comptiable with Ridgestone electronics, Prolific Technology, Inc. PL2303 Serial Port
                att_port = p_info
                break
            if p_info.vid == 0x0403 and p_info.pid == 0x6001:
                # comptiable with Future Technology Devices International, Ltd FT232 USB-Serial (UART) IC
                att_port = p_info
                break
    if not att_port:
        raise AssertionError('Can not find supported att port ....')
    return att_port
