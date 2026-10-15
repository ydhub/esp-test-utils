"""DPS3005/DPS5005 programmable power-supply driver.

The communication board exposes Modbus RTU over a serial port.  The driver
implements the two functions supported by DPS firmware: read holding registers
(0x03) and write a single register (0x06).
"""

import threading
import time
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

import serial

from ..logger import get_logger
from .serial_tools import compute_serial_port, get_all_serial_ports

logger = get_logger('devices.dps')

CH340_VID = 0x1A86
CH340_PID = 0x7523


class ModelSpec(NamedTuple):
    name: str
    max_voltage: float
    max_current: float
    current_scale: int


# DPS5015/DPS5020 use a different current scale and must be verified on real
# hardware before being added.
MODEL_SPECS = {
    3005: ModelSpec('DPS3005', 30.0, 5.0, 1000),
    5005: ModelSpec('DPS5005', 50.0, 5.0, 1000),
}


class DPSError(OSError):
    """Raised when a DPS cannot be opened, addressed, or safely configured."""


class DPS:  # pylint: disable=too-many-public-methods
    """Control a DPS programmable power supply over Modbus RTU."""

    DEFAULT_BAUDRATE = 9600
    DEFAULT_SLAVE_ADDRESS = 1
    DEFAULT_TIMEOUT = 0.5
    TRANSFER_RETRY = 3

    REG_USET = 0x00
    REG_ISET = 0x01
    REG_UOUT = 0x02
    REG_IOUT = 0x03
    REG_POUT = 0x04
    REG_UIN = 0x05
    REG_LOCK = 0x06
    REG_PROTECT = 0x07
    REG_CVCC = 0x08
    REG_ONOFF = 0x09
    REG_BLED = 0x0A
    REG_MODEL = 0x0B
    REG_VERSION = 0x0C
    REG_OVP = 0x52
    REG_OCP = 0x53
    REG_OPP = 0x54

    VOLTAGE_SCALE = 100
    POWER_SCALE = 100
    OPP_SCALE = 10

    # These safety limits are intentionally fixed. Callers cannot widen them.
    MIN_VOLTAGE = 1.8
    MAX_VOLTAGE = 4.5
    MIN_CURRENT = 0.0
    MAX_CURRENT = 5.0
    DEFAULT_CURRENT = 5.0

    PROTECTION_STATE = {0: 'none', 1: 'OVP', 2: 'OCP', 3: 'OPP'}

    READ_FUNCTION = 0x03
    WRITE_FUNCTION = 0x06

    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        slave_address: int = DEFAULT_SLAVE_ADDRESS,
        timeout: float = DEFAULT_TIMEOUT,
        serial_device: Optional[Any] = None,
    ) -> None:
        """Open a DPS communication port.

        ``serial_device`` accepts an already-open serial-compatible object and
        is primarily useful for tests.
        """
        self.port = port
        self.baudrate = baudrate
        self.slave_address = slave_address
        self._lock = threading.Lock()
        self._spec = None  # type: Optional[ModelSpec]

        if serial_device is not None:
            self.serial = serial_device
            return

        self.port = compute_serial_port(port, strict=False)
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
            )
        except serial.SerialException as e:
            raise DPSError(f'[DPS] failed to open {port}: {e}') from e

    @classmethod
    def list_candidate_ports(cls) -> List[str]:
        """Return serial ports using the DPS communication board's CH340 bridge."""
        return [
            port.device
            for port in get_all_serial_ports(include_links=True)
            if port.vid == CH340_VID and port.pid == CH340_PID
        ]

    @classmethod
    def auto_detect(
        cls,
        baudrate: int = DEFAULT_BAUDRATE,
        ports: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> 'DPS':
        """Return the first candidate that answers as a supported DPS model."""
        candidates = list(ports) if ports is not None else cls.list_candidate_ports()
        errors = []  # type: List[str]
        for port in candidates:
            try:
                device = cls(port, baudrate=baudrate, **kwargs)
            except DPSError as e:
                errors.append(f'{port}: {e}')
                continue
            try:
                name = device.model_name
            except DPSError as e:
                errors.append(f'{port}: {e}')
                device.close()
                continue
            logger.info('Found %s on %s', name, port)
            return device
        details = f'; probe errors: {"; ".join(errors)}' if errors else ''
        raise DPSError(f'[DPS] no DPS module found on {candidates} at {baudrate} baud{details}')

    def _resolve_spec(self, model: int) -> ModelSpec:
        if self._spec is None:
            if model not in MODEL_SPECS:
                raise DPSError(
                    f'[DPS] unsupported model {model} on {self.port}, known models are {sorted(MODEL_SPECS)}'
                )
            self._spec = MODEL_SPECS[model]
            logger.debug('%s identified as %s', self.port, self._spec.name)
        return self._spec

    @property
    def spec(self) -> ModelSpec:
        """Return model ratings and register resolution."""
        if self._spec is None:
            self._resolve_spec(self.get_model())
        assert self._spec is not None
        return self._spec

    @property
    def model_name(self) -> str:
        """Return the model name, for example ``DPS5005``."""
        return self.spec.name

    @property
    def current_scale(self) -> int:
        """Return the current-register scale for this model."""
        return self.spec.current_scale

    @staticmethod
    def _check_limit(name: str, value: float, hardware_max: float) -> float:
        value = float(value)
        if value <= 0 or value > hardware_max:
            raise DPSError(f'[DPS] {name} {value} out of range (0, {hardware_max}]')
        return value

    @staticmethod
    def crc16(data: bytes) -> bytes:
        """Return a Modbus CRC16 in wire-order (little endian)."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc.to_bytes(2, 'little')

    def _build_request(self, function: int, first: int, second: int) -> bytes:
        request = bytearray(6)
        request[0] = self.slave_address
        request[1] = function
        request[2:4] = first.to_bytes(2, 'big')
        request[4:6] = second.to_bytes(2, 'big')
        return bytes(request) + self.crc16(request)

    def _read_response(self, expected_length: int) -> bytes:
        response = bytearray()
        while len(response) < expected_length:
            chunk = self.serial.read(expected_length - len(response))
            if not chunk:
                break
            response.extend(chunk)
        return bytes(response)

    def _check_response(
        self,
        response: bytes,
        function: int,
        expected_length: int,
        request_data: bytes,
    ) -> None:
        if len(response) < expected_length:
            raise DPSError(f'[DPS] short response from {self.port}: {response.hex()}')
        if response[-2:] != self.crc16(response[:-2]):
            raise DPSError(f'[DPS] bad checksum from {self.port}: {response.hex()}')
        if response[0] != self.slave_address:
            raise DPSError(f'[DPS] response from slave {response[0]}, expected {self.slave_address}')
        if response[1] != function:
            raise DPSError(f'[DPS] module rejected function {function:#04x}: {response.hex()}')
        if function == self.WRITE_FUNCTION and response[2:6] != request_data:
            raise DPSError(
                f'[DPS] write echo mismatch from {self.port}: expected {request_data.hex()}, got {response[2:6].hex()}'
            )

    def _transfer(self, function: int, first: int, second: int, expected_length: int) -> bytes:
        request = self._build_request(function, first, second)
        with self._lock:
            if self.serial is None:
                raise DPSError(f'[DPS] {self.port} is closed')
            error = None  # type: Optional[Exception]
            for attempt in range(self.TRANSFER_RETRY):
                try:
                    self.serial.reset_input_buffer()
                    self.serial.write(request)
                    response = self._read_response(expected_length)
                    self._check_response(response, function, expected_length, request[2:6])
                    return response
                except (DPSError, serial.SerialException) as e:
                    error = e
                    logger.debug('Transfer to %s failed (attempt %d): %s', self.port, attempt + 1, e)
                    time.sleep(0.05)
        raise DPSError(f'[DPS] no valid answer from {self.port}: {error}')

    def _read_registers(self, address: int, count: int) -> List[int]:
        """Read holding registers starting at ``address``."""
        response = self._transfer(self.READ_FUNCTION, address, count, 5 + 2 * count)
        return [int.from_bytes(response[3 + i : 5 + i], 'big') for i in range(0, 2 * count, 2)]

    def _write_register(self, address: int, value: int) -> int:
        """Write one holding register and return the echoed value."""
        if not 0 <= value <= 0xFFFF:
            raise DPSError(f'[DPS] register value {value} does not fit in 16 bits')
        response = self._transfer(self.WRITE_FUNCTION, address, value, 8)
        return int.from_bytes(response[4:6], 'big')

    def read_status(self) -> Dict[str, Any]:
        """Read and decode the complete working state in one transaction."""
        regs = self._read_registers(self.REG_USET, 13)
        current_scale = self._resolve_spec(regs[self.REG_MODEL]).current_scale
        return {
            'voltage_set': regs[self.REG_USET] / self.VOLTAGE_SCALE,
            'current_set': regs[self.REG_ISET] / current_scale,
            'voltage_out': regs[self.REG_UOUT] / self.VOLTAGE_SCALE,
            'current_out': regs[self.REG_IOUT] / current_scale,
            'power_out': regs[self.REG_POUT] / self.POWER_SCALE,
            'voltage_in': regs[self.REG_UIN] / self.VOLTAGE_SCALE,
            'key_locked': bool(regs[self.REG_LOCK]),
            'protection': self.PROTECTION_STATE.get(regs[self.REG_PROTECT], 'unknown'),
            'mode': 'CC' if regs[self.REG_CVCC] else 'CV',
            'output': bool(regs[self.REG_ONOFF]),
            'model': regs[self.REG_MODEL],
            'version': regs[self.REG_VERSION],
        }

    def get_model(self) -> int:
        return self._read_registers(self.REG_MODEL, 1)[0]

    def get_voltage(self) -> float:
        return self._read_registers(self.REG_UOUT, 1)[0] / self.VOLTAGE_SCALE

    def get_current(self) -> float:
        return self._read_registers(self.REG_IOUT, 1)[0] / self.current_scale

    def get_power(self) -> float:
        return self._read_registers(self.REG_POUT, 1)[0] / self.POWER_SCALE

    def get_output(self) -> bool:
        return bool(self._read_registers(self.REG_ONOFF, 1)[0])

    def get_protection_state(self) -> str:
        value = self._read_registers(self.REG_PROTECT, 1)[0]
        return self.PROTECTION_STATE.get(value, 'unknown')

    def get_protection(self) -> Dict[str, float]:
        regs = self._read_registers(self.REG_OVP, 3)
        return {
            'over_voltage': regs[0] / self.VOLTAGE_SCALE,
            'over_current': regs[1] / self.current_scale,
            'over_power': regs[2] / self.OPP_SCALE,
        }

    def set_voltage(self, volts: float) -> float:
        """Set voltage in V, enforcing the fixed DUT-safe range."""
        volts = float(volts)
        if volts < self.MIN_VOLTAGE or volts > self.MAX_VOLTAGE:
            raise DPSError(f'[DPS] voltage {volts}V out of range [{self.MIN_VOLTAGE}, {self.MAX_VOLTAGE}]')
        echo = self._write_register(self.REG_USET, round(volts * self.VOLTAGE_SCALE))
        logger.info('Set voltage to %.2fV', echo / self.VOLTAGE_SCALE)
        return echo / self.VOLTAGE_SCALE

    def set_current(self, amps: float) -> float:
        """Set current limit in A, enforcing the fixed DUT-safe range."""
        amps = float(amps)
        if amps < self.MIN_CURRENT or amps > self.MAX_CURRENT:
            raise DPSError(f'[DPS] current {amps}A out of range [{self.MIN_CURRENT}, {self.MAX_CURRENT}]')
        scale = self.current_scale
        echo = self._write_register(self.REG_ISET, round(amps * scale))
        logger.info('Set current to %.3fA', echo / scale)
        return echo / scale

    def set_output(self, on: bool) -> bool:
        """Switch output on or off, refusing unsafe stored voltage settings."""
        if on:
            volts = self._read_registers(self.REG_USET, 1)[0] / self.VOLTAGE_SCALE
            if volts < self.MIN_VOLTAGE or volts > self.MAX_VOLTAGE:
                raise DPSError(
                    f'[DPS] refusing to enable output with unsafe voltage setting {volts}V; '
                    f'allowed range is [{self.MIN_VOLTAGE}, {self.MAX_VOLTAGE}]'
                )
        echo = self._write_register(self.REG_ONOFF, 1 if on else 0)
        logger.info('Output %s', 'ON' if echo else 'OFF')
        return bool(echo)

    def output_on(self) -> bool:
        return self.set_output(True)

    def output_off(self) -> bool:
        return self.set_output(False)

    def set_protection(
        self,
        over_voltage: Optional[float] = None,
        over_current: Optional[float] = None,
        over_power: Optional[float] = None,
    ) -> Dict[str, float]:
        """Program the module OVP/OCP/OPP thresholds supplied by the caller."""
        spec = self.spec
        values = (
            ('over voltage', over_voltage, self.VOLTAGE_SCALE, spec.max_voltage, self.REG_OVP),
            ('over current', over_current, spec.current_scale, spec.max_current, self.REG_OCP),
            ('over power', over_power, self.OPP_SCALE, spec.max_voltage * spec.max_current, self.REG_OPP),
        )
        for name, value, scale, hardware_max, register in values:
            if value is None:
                continue
            checked = self._check_limit(name, value, hardware_max)
            self._write_register(register, round(checked * scale))
            logger.info('Set %s protection to %s', name, checked)
        return self.get_protection()

    def set_key_lock(self, lock: bool) -> bool:
        return bool(self._write_register(self.REG_LOCK, 1 if lock else 0))

    def power_output(
        self,
        volts: float,
        amps: float = DEFAULT_CURRENT,
        output: bool = True,
    ) -> Dict[str, Any]:
        """Set voltage/current first, then optionally enable output."""
        self.set_voltage(volts)
        self.set_current(amps)
        if output:
            self.set_output(True)
        return self.read_status()

    def close(self) -> None:
        """Close the serial port without changing the output state."""
        with self._lock:
            if self.serial is not None:
                try:
                    self.serial.close()
                except OSError as e:  # pragma: no cover - defensive cleanup
                    logger.warning('Failed to close %s: %s', self.port, e)
                self.serial = None

    def __enter__(self) -> 'DPS':
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()


__all__ = ['CH340_PID', 'CH340_VID', 'DPS', 'DPSError', 'MODEL_SPECS', 'ModelSpec']
