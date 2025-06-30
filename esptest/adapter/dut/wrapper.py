from typing import Any, Optional, Type, TypeVar, Union, overload

import serial

from ...common.generator import get_next_index
from ...logger import get_logger
from ..port.base_port import RawPort
from ..port.serial_port import SerialExt, SerialPort
from .create_dut import create_dut
from .dut_base import DutBase, DutConfig
from .esp_dut import EspDut

T = TypeVar('T', bound=DutBase)
logger = get_logger('dut_wrapper')


@overload
def dut_wrapper(dut: RawPort, name: str = '', log_file: str = '') -> DutBase: ...
@overload
def dut_wrapper(dut: Union[serial.Serial, SerialPort], name: str = '', log_file: str = '') -> DutBase: ...
@overload
def dut_wrapper(dut: DutConfig, wrap_cls: Optional[Type[T]] = None) -> T: ...
@overload
def dut_wrapper(dut: Any, name: str = '', log_file: str = '', wrap_cls: Optional[Type[T]] = None) -> T: ...


def dut_wrapper(dut, name='', log_file='', wrap_cls=None):  # type: ignore
    """wrap the dut from other frameworks.

    Supported dut types:
    - serial.Serial: will be converted to ``SerialExt``
    - TBD: pytest-embedded dut
    - TBD: tiny-test-fw dut
    - TBD: ATS UartPort
    - Other objects that matched ``RawPort``.

    Args:
        dut (Any): dut_config or the dut object from other frameworks
        name (str, optional): set name for dut wrapper, not supported getting from dut class by default.
        log_file (str, optional): set name for dut wrapper, not supported getting from dut class by default.
        wrap_cls (Type, optional): customer DutClass with mixins

    Returns:
        DutBase: dut object
    """

    wrap_dut: Optional[DutBase] = None
    wrap_cls: Type[DutBase] = wrap_cls or EspDut
    assert issubclass(wrap_cls, DutBase)

    if isinstance(dut, DutConfig):
        return create_dut(dut, wrap_cls)

    if isinstance(dut, str):
        # input string is considered as a device path
        _name = name or dut.split('/')[-1]
        dut_config = DutConfig(opened_port=dut, name=_name, log_file=log_file)
        wrap_dut = wrap_cls(dut_config)
    elif isinstance(dut, serial.Serial):
        _name = name or dut.port.split('/')[-1]
        dut.__class__ = SerialExt
        dut_config = DutConfig(opened_port=dut, name=_name, log_file=log_file)
        wrap_dut = wrap_cls(dut_config)
    elif isinstance(dut, RawPort):
        _name = name
        if not _name:
            _index = get_next_index('dut')
            _name = f'dut_{_index}'
        dut_config = DutConfig(opened_port=dut, name=_name, log_file=log_file)
        wrap_dut = wrap_cls(dut_config)
    elif isinstance(dut, SerialPort):
        logger.warning(f'dut type {type(dut)} is not supported')
        # dut_config = DutConfig(opened_port=dut)
        # wrap_dut = wrap_cls(dut_config)
        wrap_dut = dut
    else:
        raise NotImplementedError(f'Not supported dut type: {type(dut)}')

    return wrap_dut  # type: ignore
