import threading

import esptest.common.compat_typing as t

from .dut_base import DutBase, DutConfig
from .esp_dut import EspDut

T = t.TypeVar('T', bound=DutBase)


class _DutFactory:
    LOCK = threading.RLock()
    DUT_STACK: t.List[DutBase] = []

    @classmethod
    def _clean(cls) -> None:
        pass

    @classmethod
    def create(cls, dut_config: DutConfig, dut_cls: t.Type[T]) -> T:
        with cls.LOCK:
            return dut_cls(dut_config)


def create_dut(dut_config: DutConfig, cls: t.Optional[t.Type[T]] = None) -> T:
    """
    Create a DUT instance based on the provided configuration.

    Args:
        dut_config (DutConfig): The configuration for the DUT.
        cls (Type[T]): The class type to instantiate, default is EspDut.

    Returns:
        EspDut: An instance of a DUT.
    """
    return _DutFactory.create(dut_config, cls or EspDut)  # type: ignore
