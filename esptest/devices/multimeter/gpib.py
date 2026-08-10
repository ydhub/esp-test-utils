"""Draft: GPIB multimeter backend (SCPI measure from ats-n2).

Ported from ATS AutoTestScript ``comm/GPIB.py`` at
e10787397ad19426fd17d9b64d97f47f768da349.
"""

import math
import time

import esptest.common.compat_typing as t

from .base import DeviceInfo, MultimeterBackend, MultimeterError
from .transport.base import GPIBTransport
from .transport.factory import open_gpib

SAMPLE_TIME_34465A = 0.0003330386740331491712707182320442
SAMPLE_TIME_34401A = 0.0006530386740331491712707182320442
MAX_SAMPLE_COUNT = 50000
MIN_OPC_TIMEOUT_S = 30
# is_busy() polls once per second, so the OPC budget must outlast the capture itself.
OPC_TIMEOUT_MARGIN_S = 10

_ALLOWED_MEASURE_KWARGS = frozenset(['max_value', 'opc_timeout_s'])


class GpibBackend(MultimeterBackend):
    """Draft: Keysight-style GPIB DMM backend (34465A / 34401A SCPI)."""

    backend_name = 'gpib'

    def __init__(
        self,
        address: t.Optional[int] = None,
        resource: t.Optional[str] = None,
        transport: t.Optional[GPIBTransport] = None,
        sample_time: float = SAMPLE_TIME_34465A,
    ) -> None:
        self._address = address
        self._resource = resource
        self._injected = transport is not None
        self._transport = transport
        self._sample_time = sample_time
        self._sample_rate_s = None  # type: t.Optional[float]

    @classmethod
    def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
        """Draft: discover GPIB DMMs; Joulescope filters are unsupported."""
        if filters.get('serial_number') is not None:
            raise NotImplementedError('serial_number filter is reserved for Joulescope; not supported by GPIB')
        if filters.get('path') is not None:
            raise NotImplementedError('path filter is reserved for Joulescope; not supported by GPIB')
        address = filters.get('address')
        resource = filters.get('resource')
        try:
            transport = open_gpib(address=address, resource=resource)
        except Exception:  # pylint: disable=broad-exception-caught
            return []
        try:
            try:
                identity = transport.ask('*IDN?')
            except Exception:  # pylint: disable=broad-exception-caught
                # An openable handle is not proof of a DMM: without *IDN? treat it as no match.
                return []
            if not identity:
                return []
            # Auto-discovery: prefer resolved values from the opened transport.
            if address is None:
                address = getattr(transport, 'address', None)
            if resource is None:
                resource = getattr(transport, 'resource', None)
            return [
                DeviceInfo(
                    backend=cls.backend_name,
                    address=address,
                    resource=resource,
                    identity=identity,
                )
            ]
        finally:
            try:
                transport.close()
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def open(self) -> None:
        """Draft: open transport unless one was injected."""
        if self._transport is not None:
            return
        self._transport = open_gpib(address=self._address, resource=self._resource)

    def close(self) -> None:
        """Draft: close the underlying transport if present."""
        if self._transport is not None:
            self._transport.close()
            if not self._injected:
                self._transport = None

    def prepare(self, sample_rate_s: float) -> None:
        """Draft: store sample period (seconds); SCPI config runs at measure time."""
        self._sample_rate_s = sample_rate_s

    def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
        """Draft: capture DC current samples; returns milliamperes."""
        unknown = set(kwargs) - _ALLOWED_MEASURE_KWARGS
        if unknown:
            raise TypeError(
                'GpibBackend.measure_current_ma() got unexpected keyword argument(s): ' + ', '.join(sorted(unknown))
            )
        max_value = float(kwargs.get('max_value', 0.1))
        opc_timeout_s = kwargs.get('opc_timeout_s')
        if opc_timeout_s is None:
            opc_timeout_s = self.default_opc_timeout_s(duration_s)
        else:
            opc_timeout_s = int(opc_timeout_s)

        if self._sample_rate_s is None:
            raise ValueError('sample_rate not set; call prepare(sample_rate_s) first')

        sample_rate = self._sample_rate_s
        sample_num = int(duration_s / sample_rate)
        self._start_measure('CURR', max_value=max_value, sample_num=sample_num, sample_rate=sample_rate)
        return self._get_measure_result(timeout=opc_timeout_s)

    @staticmethod
    def default_opc_timeout_s(duration_s: float) -> int:
        """Draft: OPC budget for a capture of ``duration_s`` seconds."""
        return max(MIN_OPC_TIMEOUT_S, int(math.ceil(duration_s)) + OPC_TIMEOUT_MARGIN_S)

    def measure_once(self, measure_type: str) -> float:
        """Draft: single-shot MEAS query; returns amperes or volts (instrument units)."""
        transport = self._require_transport()
        if measure_type == 'IDC':
            return float(transport.ask('MEAS:CURR:DC? MAX'))
        if measure_type == 'VDC':
            return float(transport.ask('MEAS:VOLT:DC? MAX'))
        if measure_type == 'IAC':
            return float(transport.ask('MEAS:CURR:AC? MAX'))
        if measure_type == 'VAC':
            return float(transport.ask('MEAS:VOLT:AC? MAX'))
        raise ValueError(f'MEASURE TYPE ERROR: {measure_type}')

    def reset(self) -> bool:
        """Draft: *RST/*CLS then wait for OPC; True if ready."""
        transport = self._require_transport()
        transport.write('*RST')
        transport.write('*CLS')
        return not self.is_busy()

    def is_busy(self, timeout: int = 10) -> bool:
        """Draft: poll *OPC?; True if still busy after timeout seconds."""
        transport = self._require_transport()
        for _ in range(timeout):
            data = transport.ask('*OPC?')
            if '1' in data:
                return False
            time.sleep(1)
        return True

    def _require_transport(self) -> GPIBTransport:
        if self._transport is None:
            raise MultimeterError('GPIB transport is not open; call open() first')
        return self._transport

    def _start_measure(
        self,
        measure_type: str,
        max_value: float,
        sample_num: int,
        sample_rate: float,
    ) -> None:
        if sample_num < 1:
            raise ValueError(
                f'given {sample_num} sample count is below 1; '
                f'measure duration is shorter than sample rate {sample_rate}'
            )
        if sample_num > MAX_SAMPLE_COUNT:
            raise ValueError(f'given {sample_num} sample count exceed max sample count {MAX_SAMPLE_COUNT}')
        if sample_rate < self._sample_time:
            raise ValueError(f'given {sample_rate} sample rate smaller than sample time {self._sample_time}')
        transport = self._require_transport()
        transport.write('DISP OFF')
        transport.write(f'CONF:{measure_type}:DC DEF,DEF')
        transport.write(f'{measure_type}:DC:RANG {max_value:f}')
        transport.write(f'{measure_type}:DC:RES MAX')
        transport.write(f'{measure_type}:DC:NPLC MIN')
        transport.write('ZERO:AUTO OFF')
        transport.write(f'{measure_type}:DC:RANG:AUTO OFF')
        transport.write('CALC:STAT OFF')
        # TODO(draft): TRIG:SOUR IMM + INIT then *TRG after OPC matches ATS
        # e10787397ad19426fd17d9b64d97f47f768da349. On Keysight IMM, INIT often
        # starts the capture; *TRG may be a no-op or wrong vs BUS. Confirm on HW
        # before changing this sequence.
        transport.write('TRIG:SOUR IMM')
        delay = sample_rate - self._sample_time
        transport.write(f'TRIG:DEL {delay:f}')
        transport.write(f'SAMP:COUN {sample_num:d}')
        transport.write('TRIG:COUN 1')
        transport.write('INIT')

    def _get_measure_result(self, timeout: int = 30) -> t.List[float]:
        transport = self._require_transport()
        if self.is_busy(timeout):
            raise MultimeterError('device is busy (OPC timeout)')
        # TODO(draft): see TRIG:SOUR IMM note in _start_measure — *TRG after OPC.
        transport.write('*TRG')
        result = transport.ask('FETC?')
        parts = result.split(',')
        return [float(item) * 1000.0 for item in parts]
