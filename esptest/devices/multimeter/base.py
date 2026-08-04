"""Draft: Multimeter backend registry and base classes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import esptest.common.compat_typing as t

_REGISTRY: t.Dict[str, t.Type['MultimeterBackend']] = {}


class MultimeterError(OSError):
    """Draft: Raised when multimeter operations fail."""


@dataclass
class DeviceInfo:
    """Draft: Describes a discovered multimeter device."""

    backend: str
    address: t.Optional[int] = None
    resource: t.Optional[str] = None
    identity: t.Optional[str] = None


class MultimeterBackend(ABC):
    """Draft: Abstract base class for multimeter backends."""

    backend_name: str = ''

    def __init_subclass__(cls, **kwargs: t.Any) -> None:
        super().__init_subclass__(**kwargs)
        name = getattr(cls, 'backend_name', '')
        if name:
            _REGISTRY[name] = cls

    @classmethod
    @abstractmethod
    def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]: ...

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def prepare(self, sample_rate_s: float) -> None: ...

    @abstractmethod
    def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]: ...


def get_backend_class(name: str) -> t.Type[MultimeterBackend]:
    """Draft: Look up a registered backend class by name."""
    return _REGISTRY[name]


def registered_backends() -> t.Dict[str, t.Type[MultimeterBackend]]:
    """Draft: Return the backend registry."""
    return _REGISTRY
