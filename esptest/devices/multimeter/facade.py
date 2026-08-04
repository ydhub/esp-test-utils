"""Draft: Multimeter facade (PowerMeter-like lifecycle)."""

import esptest.common.compat_typing as t

from .base import MultimeterBackend, get_backend_class


class Multimeter:
    """Draft: Unified multimeter facade; GPIB first, API may change."""

    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        log_path: t.Optional[str] = None,
        sample_rate: t.Optional[float] = None,
        backend: str = 'gpib',
        address: t.Optional[int] = None,
        resource: t.Optional[str] = None,
        **backend_kwargs: t.Any,
    ) -> None:
        self.log_path = log_path
        self._sample_rate = None  # type: t.Optional[float]
        self.sampling_frequency = None  # type: t.Optional[int]
        self._backend_name = backend
        self._address = address
        self._resource = resource
        self._backend_kwargs = backend_kwargs
        self._backend = None  # type: t.Optional[MultimeterBackend]
        if sample_rate is not None:
            self.sample_rate = sample_rate

    @property
    def sample_rate(self) -> t.Optional[float]:
        """Draft: Sample period in seconds."""
        return self._sample_rate

    @sample_rate.setter
    def sample_rate(self, value: t.Optional[float]) -> None:
        if value is not None and value <= 0:
            raise ValueError(f'sample_rate must be a positive number of seconds, got {value}')
        self._sample_rate = value
        self.sampling_frequency = int(round(1.0 / value)) if value is not None else None

    def device_start(self) -> None:
        """Draft: Open backend and prepare with sample_rate."""
        if self._sample_rate is None:
            raise ValueError('sample_rate must be set before device_start()')
        if self._backend is not None:
            self.device_close()
        backend_cls = get_backend_class(self._backend_name)
        kwargs = dict(self._backend_kwargs)
        if self._address is not None:
            kwargs.setdefault('address', self._address)
        if self._resource is not None:
            kwargs.setdefault('resource', self._resource)
        self._backend = backend_cls(**kwargs)
        self._backend.open()
        self._backend.prepare(self._sample_rate)

    def device_close(self) -> None:
        """Draft: Close backend; idempotent."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None

    def measure_current(self, measure_time: float, **kwargs: t.Any) -> t.List[float]:
        """Draft: Blocking current capture; returns milliamperes."""
        backend = self._require_backend()
        return backend.measure_current_ma(measure_time, **kwargs)

    def measure_current_once(self) -> float:
        """Draft: Single-shot DC current (instrument units, typically amperes)."""
        return self._measure_once('IDC')

    def measure_voltage_once(self) -> float:
        """Draft: Single-shot DC voltage (instrument units, typically volts)."""
        return self._measure_once('VDC')

    def _measure_once(self, measure_type: str) -> float:
        backend = self._require_backend()
        if not hasattr(backend, 'measure_once'):
            raise NotImplementedError(f'backend {self._backend_name!r} does not support measure_once')
        # Optional backend method (not on MultimeterBackend ABC).
        return float(backend.measure_once(measure_type))  # type: ignore[attr-defined]  # pylint: disable=no-member

    def _require_backend(self) -> MultimeterBackend:
        if self._backend is None:
            raise RuntimeError('device not started; call device_start() first')
        return self._backend
