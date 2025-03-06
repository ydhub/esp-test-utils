import re
import time
from contextlib import contextmanager
from typing import Generator
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self


import enum


import usb.core  # type: ignore
import serial
from serial.tools.list_ports_common import ListPortInfo

from ..logger import get_logger
from .serial_tools import get_all_serial_ports
from ..common.decorators import deprecated

logger = get_logger('devices')


class AttenuatorError(OSError): ...


class AttType(enum.StrEnum):
    # wuyou electronics(Dc-6ghz 90db)
    WUYOU = 'wuyou'
    # Ridgestone electronics, Prolific Technology, Inc. PL2303 Serial Port
    RIDGESTONE = 'ridgestone'
    # Future Technology Devices International, Ltd FT232 USB-Serial (UART)
    # TODO: vid/pid is sam
    FUTURE_TECHNOLOGY = 'future_technology'
    # Mini Circuits (USB Port)
    MINI_CIRCUITS = 'mini_circuits'


ATT_ID_INFO = {
    # Serial Device
    AttType.WUYOU: {'vid': 0x0483, 'pid': 0x5740},
    AttType.RIDGESTONE: {'vid': 0x067B, 'pid': 0x2303},
    AttType.FUTURE_TECHNOLOGY: {'vid': 0x0403, 'pid': 0x6001},
    # USB Device
    AttType.MINI_CIRCUITS: {'vid': 0x20CE, 'pid': 0x0023},
}


class AttDevice:
    SUPPORTED_TYPES: List[AttType] = []
    READ_DELAY: float = 0.5

    def __init__(self, device: str, att_type: AttType) -> None:
        self.att_type = att_type
        self.device = device
        logger.info(f'Opening AttDevice {att_type}: {device}')

    @property
    def min(self) -> float:
        return 0

    @property
    def max(self) -> float:
        return {
            AttType.MINI_CIRCUITS: 95,
            AttType.WUYOU: 92,
            AttType.RIDGESTONE: 62,
            AttType.FUTURE_TECHNOLOGY: 62,
        }.get(self.att_type, 60)

    def set_att(self, att: float, att_fix: bool = False) -> bool:
        raise NotImplementedError()

    @classmethod
    def get_type_by_id(cls, vid: int, pid: int) -> AttType:
        for att_type, _id in ATT_ID_INFO.items():
            if att_type not in cls.SUPPORTED_TYPES:
                continue
            if vid == _id['vid'] and pid == _id['pid']:
                return att_type
        raise AttenuatorError(f'Not support Attenuator type: {hex(vid)}:{hex(pid)}')


class SerialAttDev(AttDevice):
    SUPPORTED_TYPES = [AttType.WUYOU, AttType.RIDGESTONE, AttType.FUTURE_TECHNOLOGY]

    @classmethod
    def get_ser_port_info(
        cls,
        device: Optional[str] = None,
    ) -> ListPortInfo:
        port_info_list = get_all_serial_ports()
        for p_info in port_info_list:
            if device and device in (p_info.device, p_info.name, p_info.location):
                return p_info
        for p_info in port_info_list:
            if any(
                p_info.vid == _id['vid'] and p_info.pid == _id['pid']
                for _typ, _id in ATT_ID_INFO.items()
                if _typ in cls.SUPPORTED_TYPES
            ):
                return p_info
        raise AttenuatorError(f'Failed to get serial att port info with: device={device}')

    @contextmanager
    def open_ser(self) -> Generator[serial.Serial, None, None]:
        with serial.Serial(self.device, baudrate=9600, rtscts=False, timeout=0.1) as ser_inst:
            yield ser_inst

    def set_att(self, att: float, att_fix: bool = False) -> bool:
        logger.debug(f'set_att: {att}')
        assert self.min <= att <= self.max
        with self.open_ser() as ser_inst:
            if self.att_type in (AttType.RIDGESTONE, AttType.FUTURE_TECHNOLOGY):
                assert int(att) == att
                att = int(att)
                # fix att based on experience
                if att_fix:
                    if att >= 33 and (att - 30 + 1) % 4 == 0:
                        att = att - 1
                    elif att >= 33 and (att - 30) % 4 == 0:
                        att = att + 1

                # cmd_hex = f'7e7e10{att:02x}{0x10+att:x}'
                # exp_res_hex = f'7e7e20{att:02x}00{0x20+att:x}'
                cmd = bytes([0x7E, 0x7E, 0x10, att, 0x10 + att])
                exp_res = bytes([0x7E, 0x7E, 0x20, att, 0x20 + att])

                ser_inst.write(cmd)
                time.sleep(self.READ_DELAY)
                resp = ser_inst.read(20)
                if resp == exp_res:
                    return True
            elif self.att_type == AttType.WUYOU:
                # TODO: may support float?
                assert isinstance(att, int)
                ser_inst.write(f'att-{att:03d}.00\r\n'.encode())
                time.sleep(self.READ_DELAY)
                assert b'attOK' in ser_inst.read(20)
                ser_inst.write(b'READ\r\n')
                time.sleep(self.READ_DELAY)
                _raw_data = ser_inst.read(200).decode('utf-8', errors='ignore')
                match = re.match(re.compile(r'ATT = -(\d+).00'), _raw_data)
                assert match and int(match.group(1)) == att, 'Set att fail!'
                return True
        return False

    @classmethod
    def create(cls, device: Optional[str] = None, att_type: Optional[AttType] = None) -> 'Self':
        port_info = cls.get_ser_port_info(device)
        att_type = cls.get_type_by_id(port_info.vid, port_info.pid)
        return cls(device=port_info.device, att_type=att_type)


class USBAttDev(AttDevice):
    SUPPORTED_TYPES = [
        # https://www.minicircuits.com/softwaredownload/Prog_Examples_Troubleshooting.pdf Page25
        AttType.MINI_CIRCUITS,
    ]
    DEV_LOCATION_PATTERN = re.compile(r'(\d)-([\d\.]*\d)')

    def __init__(self, device: str, att_type: AttType) -> None:
        super().__init__(device, att_type)
        assert device
        self.usb_dev = self.find_usb_dev(location=device, att_type=att_type)

    @classmethod
    def parse_location(cls, location: str) -> Tuple[int, Tuple[int, ...]]:
        match = cls.DEV_LOCATION_PATTERN.match(location)
        assert match
        return int(match.group(1)), tuple(map(int, match.group(2).split('.')))

    @classmethod
    def find_usb_dev(cls, location: Optional[str], att_type: Optional[AttType]) -> usb.core.Device:
        if location:
            bus, port_numbers = cls.parse_location(location)
            dev = usb.core.find(bus=bus, port_numbers=port_numbers)
        else:
            for typ in cls.SUPPORTED_TYPES:
                if att_type and att_type != typ:
                    continue
                vid = ATT_ID_INFO[typ]['vid']
                pid = ATT_ID_INFO[typ]['pid']
                dev = usb.core.find(idVendor=vid, idProduct=pid)
                break
        if not dev:
            raise AttenuatorError(f'Can not find USB Attenuator with: location={location},att_type={att_type}')
        return dev

    @contextmanager
    def config_usb(self) -> Generator[usb.core.Device, None, None]:
        for configuration in self.usb_dev:
            for interface in configuration:
                ifnum = interface.bInterfaceNumber
                if not self.usb_dev.is_kernel_driver_active(ifnum):
                    continue
                try:
                    self.usb_dev.detach_kernel_driver(ifnum)
                except usb.core.USBError as e:
                    raise AttenuatorError('Fail to restore att') from e
        # set the active configuration. with no args we use first config.
        self.usb_dev.set_configuration()
        yield self.usb_dev
        usb.util.dispose_resources(self.usb_dev)

    def set_att(self, att: float, att_fix: bool = False) -> bool:
        logger.debug(f'set_att: {att}')
        assert self.att_type == AttType.MINI_CIRCUITS, 'USBAttDevice only support MINI_CIRCUITS now'
        assert self.min <= att <= self.max
        with self.config_usb() as dev:

            def read_dev_data() -> str:
                # read: endpoint, size
                raw_data = dev.read(0x81, 64)
                res = ''
                for val in raw_data:
                    if not 0 < val < 255:
                        break
                    res += chr(val)
                return res

            # dev.write(1,"*:CHAN:1:SETATT:11.25;")
            cmd = f'*:CHAN:1:SETATT:{att:.3f};'
            dev.write(1, cmd)
            resp = read_dev_data()
            # resp: *0 or *1 or *2
            # 0: too small, 1: success, 2: too large
            assert resp[1] == '1'

            # return all channels attenuation
            dev.write(1, '*:ATT?')
            resp = read_dev_data()
            # resp: * xx.xx
            resp_att = float(resp[1:])
            assert resp_att == att
            return True

    @classmethod
    def create(cls, device: Optional[str] = None, att_type: Optional[AttType] = None) -> 'Self':
        usb_dev = cls.find_usb_dev(device, att_type)
        # usb_dev.port_numbers: Tuple[int, ...]
        # location format: '1-x.x.x'
        location = f'{usb_dev.bus}-{".".join(map(str, usb_dev.port_numbers))}'
        att_type = cls.get_type_by_id(usb_dev.idVendor, usb_dev.idProduct)
        return cls(device=location, att_type=att_type)


@deprecated('find_att_port is deprecated, use find_att_dev and dev.set_att instead')
def find_att_port(port: Optional[str] = None) -> ListPortInfo:
    # Deprecated
    return SerialAttDev.get_ser_port_info(port)


def find_att_dev(
    device: Optional[str] = None,
    att_type: Optional[AttType] = None,
) -> AttDevice:
    if not att_type or att_type in USBAttDev.SUPPORTED_TYPES:
        try:
            return USBAttDev.create(device, att_type=att_type)
        except AttenuatorError:
            pass

    if not att_type or att_type in SerialAttDev.SUPPORTED_TYPES:
        try:
            return SerialAttDev.create(device=device, att_type=att_type)
        except AttenuatorError:
            pass

    raise AttenuatorError(f'Can not find att device with: device={device},type={att_type}')


@deprecated('set_att can only be used when there is only one attenuator device connected')
def set_att(port: Union[ListPortInfo, str], att: float, att_fix: bool = False) -> bool:
    if isinstance(port, ListPortInfo):
        att_type = SerialAttDev.get_type_by_id(port.vid, port.pid)
        att_dev: AttDevice = SerialAttDev(device=port.device, att_type=att_type)
    else:
        att_dev = find_att_dev(port)
    logger.info(f'Find att device at {att_dev.device}, type: {att_dev.att_type}')
    return att_dev.set_att(att, att_fix)
