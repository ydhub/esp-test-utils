"""Hardware-free tests for the DPS Modbus driver."""

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from esptest.devices import dps as dps_module
from esptest.devices.dps import DPS, DPSError


class FakeSerial:
    def __init__(
        self,
        model: int = 5005,
        slave_address: int = 1,
        corrupt_first: int = 0,
        wrong_echo_first: int = 0,
    ) -> None:
        self.registers: Dict[int, int] = {
            0x00: 473,
            0x01: 2000,
            0x02: 0,
            0x03: 0,
            0x04: 0,
            0x05: 1208,
            0x06: 0,
            0x07: 0,
            0x08: 0,
            0x09: 0,
            0x0A: 4,
            0x0B: model,
            0x0C: 14,
            0x52: 5100,
            0x53: 5200,
            0x54: 265,
        }
        self.slave_address = slave_address
        self.corrupt_first = corrupt_first
        self.wrong_echo_first = wrong_echo_first
        self.requests: List[bytes] = []
        self.closed = False
        self._pending = b''

    def reset_input_buffer(self) -> None:
        self._pending = b''

    def read(self, size: int) -> bytes:
        data, self._pending = self._pending[:size], self._pending[size:]
        return data

    def close(self) -> None:
        self.closed = True

    def write(self, request: bytes) -> int:
        self.requests.append(request)
        self._pending = self._respond(request)
        return len(request)

    def _respond(self, request: bytes) -> bytes:
        function = request[1]
        first = int.from_bytes(request[2:4], 'big')
        second = int.from_bytes(request[4:6], 'big')
        if function == DPS.READ_FUNCTION:
            payload = bytearray([self.slave_address, DPS.READ_FUNCTION, 2 * second])
            for address in range(first, first + second):
                payload.extend(self.registers.get(address, 0).to_bytes(2, 'big'))
        else:
            self.registers[first] = second
            payload = bytearray(request[:6])
            if self.wrong_echo_first > 0:
                self.wrong_echo_first -= 1
                payload[4:6] = ((second + 1) & 0xFFFF).to_bytes(2, 'big')
        response = bytes(payload) + DPS.crc16(payload)
        if self.corrupt_first > 0:
            self.corrupt_first -= 1
            response = response[:-1] + bytes([response[-1] ^ 0xFF])
        return response


def make_device(model: int = 5005, **kwargs: Any) -> Any:
    fake = FakeSerial(model=model)
    return DPS('/dev/fake', serial_device=fake, **kwargs), fake


def test_crc16_matches_modbus_reference() -> None:
    frame = bytes.fromhex('010304138d000eef58')
    assert DPS.crc16(frame[:-2]) == frame[-2:]


def test_explicit_port_accepts_usb_location(monkeypatch: Any) -> None:
    fake = FakeSerial()
    monkeypatch.setattr(dps_module, 'compute_serial_port', lambda port, strict: '/dev/ttyUSB3')
    monkeypatch.setattr(dps_module.serial, 'Serial', lambda **kwargs: fake)

    device = DPS('1-5.1')

    assert device.port == '/dev/ttyUSB3'


def test_candidate_ports_use_shared_serial_discovery(monkeypatch: Any) -> None:
    ports = [
        SimpleNamespace(device='/dev/ttyUSB0', vid=dps_module.CH340_VID, pid=0),
        SimpleNamespace(device='/dev/ttyUSB3', vid=0x1A86, pid=0x7523),
    ]
    monkeypatch.setattr(dps_module, 'get_all_serial_ports', lambda include_links: ports)

    assert DPS.list_candidate_ports() == ['/dev/ttyUSB3']


def test_read_status_decodes_every_field() -> None:
    device, _ = make_device()
    status = device.read_status()
    assert status == {
        'voltage_set': 4.73,
        'current_set': 2.0,
        'voltage_out': 0.0,
        'current_out': 0.0,
        'power_out': 0.0,
        'voltage_in': 12.08,
        'key_locked': False,
        'protection': 'none',
        'mode': 'CV',
        'output': False,
        'model': 5005,
        'version': 14,
    }


def test_supported_models_share_the_register_map() -> None:
    device, _ = make_device(model=3005)
    assert device.read_status()['current_set'] == 2.0
    assert device.model_name == 'DPS3005'
    assert device.spec.max_voltage == 30.0


def test_status_read_caches_model() -> None:
    device, fake = make_device()
    device.read_status()
    requests = len(fake.requests)
    assert device.model_name == 'DPS5005'
    assert len(fake.requests) == requests


def test_unknown_model_is_refused() -> None:
    device, _ = make_device(model=5020)
    with pytest.raises(DPSError, match='unsupported model 5020'):
        device.read_status()


def test_set_voltage_and_current_scale_registers() -> None:
    device, fake = make_device()
    assert device.set_voltage(3.3) == 3.3
    assert device.set_current(1.5) == 1.5
    assert fake.registers[DPS.REG_USET] == 330
    assert fake.registers[DPS.REG_ISET] == 1500


@pytest.mark.parametrize('volts', [DPS.MIN_VOLTAGE, 3.3, DPS.MAX_VOLTAGE])
def test_voltage_inside_fixed_range_is_accepted(volts: float) -> None:
    device, _ = make_device()
    assert device.set_voltage(volts) == volts


@pytest.mark.parametrize('volts', [-1, 0, 1.7, 4.6, 50])
def test_voltage_outside_fixed_range_is_not_written(volts: float) -> None:
    device, fake = make_device()
    with pytest.raises(DPSError, match='out of range'):
        device.set_voltage(volts)
    assert fake.requests == []


@pytest.mark.parametrize('amps', [DPS.MIN_CURRENT, 2.5, DPS.MAX_CURRENT])
def test_current_inside_fixed_range_is_accepted(amps: float) -> None:
    device, _ = make_device()
    assert device.set_current(amps) == amps


@pytest.mark.parametrize('amps', [-1, 5.1])
def test_current_outside_fixed_range_is_not_written(amps: float) -> None:
    device, fake = make_device()
    with pytest.raises(DPSError, match='out of range'):
        device.set_current(amps)
    assert fake.requests == []


def test_output_toggle_and_power_output_write_order() -> None:
    device, fake = make_device()
    status = device.power_output(3.3, 1.5)
    assert status['output'] is True
    written = [int.from_bytes(request[2:4], 'big') for request in fake.requests if request[1] == DPS.WRITE_FUNCTION]
    assert written == [DPS.REG_USET, DPS.REG_ISET, DPS.REG_ONOFF]
    assert device.output_off() is False


def test_output_on_refuses_unsafe_stored_voltage() -> None:
    device, fake = make_device()
    fake.registers[DPS.REG_USET] = 3000

    with pytest.raises(DPSError, match='refusing to enable output'):
        device.output_on()

    assert fake.registers[DPS.REG_ONOFF] == 0


def test_power_output_uses_default_current() -> None:
    device, fake = make_device()
    device.power_output(3.3)
    assert DPS.DEFAULT_CURRENT == 5.0
    assert fake.registers[DPS.REG_ISET] == 5000


def test_limits_cannot_be_widened_by_caller() -> None:
    with pytest.raises(TypeError):
        make_device(max_voltage=50.0)
    assert not hasattr(DPS, 'set_limits')
    assert not hasattr(DPS, 'read_registers')
    assert not hasattr(DPS, 'write_register')


def test_protection_writes_only_supplied_thresholds() -> None:
    device, fake = make_device()
    protection = device.set_protection(over_voltage=3.6, over_current=1.0)
    assert fake.registers[DPS.REG_OVP] == 360
    assert fake.registers[DPS.REG_OCP] == 1000
    assert fake.registers[DPS.REG_OPP] == 265
    assert protection == {'over_voltage': 3.6, 'over_current': 1.0, 'over_power': 26.5}


def test_over_power_protection_uses_tenth_watt_scale() -> None:
    device, fake = make_device()
    protection = device.set_protection(over_power=5.0)
    assert fake.registers[DPS.REG_OPP] == 50
    assert protection['over_power'] == 5.0


def test_protection_above_hardware_limit_is_refused() -> None:
    device, fake = make_device()
    with pytest.raises(DPSError, match='over voltage'):
        device.set_protection(over_voltage=device.spec.max_voltage + 1)
    assert fake.registers[DPS.REG_OVP] == 5100


def test_transfer_retries_corrupt_response() -> None:
    fake = FakeSerial(corrupt_first=1)
    device = DPS('/dev/fake', serial_device=fake)
    assert device.get_model() == 5005
    assert len(fake.requests) == 2


def test_transfer_retries_mismatched_write_echo() -> None:
    fake = FakeSerial(wrong_echo_first=1)
    device = DPS('/dev/fake', serial_device=fake)
    assert device.set_voltage(3.3) == 3.3
    assert len(fake.requests) == 2


def test_transfer_stops_at_retry_limit() -> None:
    fake = FakeSerial(corrupt_first=DPS.TRANSFER_RETRY)
    device = DPS('/dev/fake', serial_device=fake)
    with pytest.raises(DPSError, match='no valid answer'):
        device.get_model()
    assert len(fake.requests) == DPS.TRANSFER_RETRY


def test_auto_detect_skips_non_answering_and_unknown_devices(monkeypatch: Any) -> None:
    silent = FakeSerial()
    silent.write = lambda request: len(request)  # type: ignore
    unknown = FakeSerial(model=1234)
    answering = FakeSerial()
    devices = {'/dev/silent': silent, '/dev/unknown': unknown, '/dev/dps': answering}

    monkeypatch.setattr(DPS, 'list_candidate_ports', classmethod(lambda cls: list(devices)))
    monkeypatch.setattr('serial.Serial', lambda port, **kwargs: devices[port])

    device = DPS.auto_detect()
    assert device.port == '/dev/dps'
    assert unknown.closed is True


def test_auto_detect_raises_when_no_candidates() -> None:
    with pytest.raises(DPSError, match='no DPS module found'):
        DPS.auto_detect(ports=[])


def test_auto_detect_reports_unsupported_model(monkeypatch: Any) -> None:
    stranger = FakeSerial(model=5020)
    monkeypatch.setattr(dps_module, 'compute_serial_port', lambda port, strict: port)
    monkeypatch.setattr(dps_module.serial, 'Serial', lambda port, **kwargs: stranger)

    with pytest.raises(DPSError, match='unsupported model 5020'):
        DPS.auto_detect(ports=['/dev/stranger'])


def test_context_manager_closes_port() -> None:
    device, fake = make_device()
    with device as handle:
        assert handle is device
    assert fake.closed is True
    assert device.serial is None
    with pytest.raises(DPSError, match='/dev/fake is closed'):
        device.get_model()
