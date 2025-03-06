from typing import Any
from typing import Optional
from typing import overload
from typing import Type
from typing import TypeVar
from typing import Union

import serial

from ...devices import SerialDut
from ..base_port import RawPort
from .dut_base import DutPort

T = TypeVar('T', bound=DutPort)


@overload
def dut_wrapper(dut: RawPort, name: str = '', log_file: str = '') -> DutPort: ...
@overload
def dut_wrapper(dut: Union[serial.Serial, SerialDut], name: str = '', log_file: str = '') -> SerialDut: ...
@overload
def dut_wrapper(dut: Any, name: str = '', log_file: str = '', wrap_cls: Optional[Type[T]] = None) -> T: ...


def dut_wrapper(dut, name='', log_file='', wrap_cls=None):  # type: ignore
    """wrap the dut from other frameworks.

    Supported dut types:
    - SerialPort
    - serial.Serial: will be converted to ``SerialPort``
    - TBD: pytest-embedded dut
    - TBD: tiny-test-fw dut
    - TBD: ATS UartPort
    - Other objects that matched ``RawPort``.

    Args:
        dut (Any): the dut object from other frameworks
        name (str, optional): set name for dut wrapper, not supported getting from dut class by default.
        log_file (str, optional): set name for dut wrapper, not supported getting from dut class by default.
        wrap_cls (Type, optional): customer DutClass with mixins

    Returns:
        DutPort: dut object
    """
    wrap_dut: Optional[DutPort] = None

    if isinstance(dut, SerialDut):
        wrap_dut = dut
        if name and name != wrap_dut.name:
            wrap_dut.name = name
        if log_file and log_file != wrap_dut.log_file:
            wrap_dut.log_file = log_file
    elif isinstance(dut, serial.Serial):
        wrap_dut = SerialDut(dut, name, log_file)
    elif isinstance(dut, RawPort):
        wrap_dut = DutPort(dut, name, log_file)
    else:
        raise NotImplementedError(f'Not supported dut type: {type(dut)}')

    if wrap_cls:
        assert issubclass(wrap_cls, DutPort)
        wrap_dut.__class__ = wrap_cls
    return wrap_dut  # type: ignore
