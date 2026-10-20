"""Hardware-free tests for the DPS Modbus driver."""

from typing import Any, Dict, List, Optional
from unittest import mock

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
        wrong_byte_count_first: int = 0,
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
        self.wrong_byte_count_first = wrong_byte_count_first
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
            if self.wrong_byte_count_first > 0:
                self.wrong_byte_count_first -= 1
                payload[2] += 2
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


def make_device(model: int = 5005, fake: Optional[FakeSerial] = None, **kwargs: Any) -> Any:
    fake = fake or FakeSerial(model=model)
    with mock.patch.object(dps_module, 'compute_serial_port', return_value='/dev/fake'):
        with mock.patch.object(dps_module.serial, 'Serial', return_value=fake):
            return DPS('/dev/fake', **kwargs), fake


def test_crc16_matches_modbus_reference() -> None:
    frame = bytes.fromhex('010304138d000eef58')
    assert DPS.crc16(frame[:-2]) == frame[-2:]


def test_explicit_port_accepts_usb_location(monkeypatch: Any) -> None:
    fake = FakeSerial()
    serial_kwargs: Dict[str, Any] = {}

    def open_serial(**kwargs: Any) -> FakeSerial:
        serial_kwargs.update(kwargs)
        return fake

    monkeypatch.setattr(dps_module, 'compute_serial_port', lambda port, strict: '/dev/ttyUSB3')
    monkeypatch.setattr(dps_module.serial, 'Serial', open_serial)

    device = DPS('1-5.1')

    assert device.port == '/dev/ttyUSB3'
    assert serial_kwargs['timeout'] == DPS.DEFAULT_TIMEOUT
    assert serial_kwargs['write_timeout'] == DPS.DEFAULT_TIMEOUT
    device.close()
    assert fake.closed is True


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


@pytest.mark.parametrize('volts', [0, 1.7, 3.3, 4.6, 50])
def test_voltage_is_not_restricted_by_software(volts: float) -> None:
    device, _ = make_device()
    assert device.set_voltage(volts) == volts


def test_negative_voltage_cannot_be_encoded_as_a_register() -> None:
    device, fake = make_device()
    with pytest.raises(DPSError, match='does not fit'):
        device.set_voltage(-1)
    assert fake.requests == []


@pytest.mark.parametrize('amps', [0, 2.5, 5.0, 5.1])
def test_current_is_not_restricted_by_software(amps: float) -> None:
    device, _ = make_device()
    assert device.set_current(amps) == amps


def test_negative_current_cannot_be_encoded_as_a_register() -> None:
    device, fake = make_device()
    with pytest.raises(DPSError, match='does not fit'):
        device.set_current(-1)
    assert all(request[1] != DPS.WRITE_FUNCTION for request in fake.requests)


def test_power_output_changes_voltage_without_disabling_active_output() -> None:
    device, fake = make_device()
    fake.registers[DPS.REG_ONOFF] = 1

    status = device.power_output(3.3, 1.5)

    assert status['output'] is True
    written = [int.from_bytes(request[2:4], 'big') for request in fake.requests if request[1] == DPS.WRITE_FUNCTION]
    assert written == [DPS.REG_USET, DPS.REG_ISET, DPS.REG_ONOFF]
    assert device.output_off() is False


def test_power_output_can_leave_output_disabled() -> None:
    device, fake = make_device()
    fake.registers[DPS.REG_ONOFF] = 1

    status = device.power_output(3.3, 1.5, output=False)

    assert status['output'] is False
    assert status['voltage_set'] == 4.73
    assert status['current_set'] == 2.0
    written = [int.from_bytes(request[2:4], 'big') for request in fake.requests if request[1] == DPS.WRITE_FUNCTION]
    assert written == [DPS.REG_ONOFF]


def test_output_on_accepts_stored_voltage_without_software_limit() -> None:
    device, fake = make_device()
    fake.registers[DPS.REG_USET] = 3000

    assert device.output_on() is True
    assert fake.registers[DPS.REG_ONOFF] == 1


@pytest.mark.parametrize('amps', [-1, 100])
def test_power_output_rejects_unencodable_current_before_writing_voltage(amps: float) -> None:
    device, fake = make_device()
    fake.registers[DPS.REG_ONOFF] = 1

    with pytest.raises(DPSError, match='does not fit'):
        device.power_output(3.3, amps)

    assert fake.registers[DPS.REG_USET] == 473
    assert fake.registers[DPS.REG_ISET] == 2000
    assert fake.registers[DPS.REG_ONOFF] == 1
    assert all(request[1] != DPS.WRITE_FUNCTION for request in fake.requests)


def test_power_output_preserves_current_when_amps_is_omitted() -> None:
    device, fake = make_device()

    device.power_output(3.3)

    assert fake.registers[DPS.REG_ISET] == 2000
    written = [int.from_bytes(request[2:4], 'big') for request in fake.requests if request[1] == DPS.WRITE_FUNCTION]
    assert DPS.REG_ISET not in written


def test_raw_register_methods_are_not_public() -> None:
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


def test_protection_checks_every_threshold_before_writing() -> None:
    device, fake = make_device()
    with pytest.raises(DPSError, match='over current'):
        device.set_protection(over_voltage=3.6, over_current=10)
    assert fake.registers[DPS.REG_OVP] == 5100
    assert fake.registers[DPS.REG_OCP] == 5200
    assert all(request[1] != DPS.WRITE_FUNCTION for request in fake.requests)


def test_transfer_retries_corrupt_response() -> None:
    fake = FakeSerial(corrupt_first=1)
    device, _ = make_device(fake=fake)
    assert device.get_model() == 5005
    assert len(fake.requests) == 2


def test_transfer_retries_mismatched_write_echo() -> None:
    fake = FakeSerial(wrong_echo_first=1)
    device, _ = make_device(fake=fake)
    assert device.set_voltage(3.3) == 3.3
    assert len(fake.requests) == 2


def test_transfer_retries_mismatched_read_byte_count() -> None:
    fake = FakeSerial(wrong_byte_count_first=1)
    device, _ = make_device(fake=fake)
    assert device.get_model() == 5005
    assert len(fake.requests) == 2


def test_transfer_stops_at_retry_limit() -> None:
    fake = FakeSerial(corrupt_first=DPS.TRANSFER_RETRY)
    device, _ = make_device(fake=fake)
    with pytest.raises(DPSError, match='no valid answer'):
        device.get_model()
    assert len(fake.requests) == DPS.TRANSFER_RETRY


def test_context_manager_closes_serial_port() -> None:
    device, fake = make_device()
    with device as handle:
        assert handle is device
    assert fake.closed is True
    assert device.serial is None
    with pytest.raises(DPSError, match='/dev/fake is closed'):
        device.get_model()
