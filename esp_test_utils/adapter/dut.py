import abc
import re
from typing import Any
from typing import AnyStr
from typing import Optional
from typing import Union


class BaseDut(metaclass=abc.ABCMeta):
    """Define a minimum Dut class, the dut objects should at least support these methods

    the dut should at least support these methods:
    - write() with parameters: data[str]
    - expect() with parameters: pattern[str or re.Pattern], timeout[int] (seconds)
    """

    @classmethod
    def __subclasshook__(cls, subclass: object) -> bool:
        return (
            hasattr(subclass, 'write')
            and callable(subclass.write)
            and hasattr(subclass, 'expect')
            and callable(subclass.expect)
        )

    def write(self, data: AnyStr) -> None:
        """write string"""
        raise NotImplementedError('Dut class should implement this method')

    def expect(self, pattern: Union[str, bytes, re.Pattern], **kwargs: Any) -> Optional[re.Match]:
        """For dut classes from other test frameworks, must support input pattern types re.Pattern and str"""
        raise NotImplementedError('Dut class should implement this method')


class DutWrapper:
    """Wrapper the dut class, to make it the same for all test methods in this package."""

    def __init__(self, dut: Any) -> None:
        self._dut = dut

    def __enter__(self) -> 'DutWrapper':
        return self

    def __exit__(self, exc_type, exc_value, trace) -> None:  # type: ignore
        """Always close the dut serial and clean resources before exiting."""
        if self._dut.hasattr('close'):
            self._dut.close()


def dut_wrapper(dut: Any) -> DutWrapper:
    """wrap the dut from other frameworks.

    Supported dut types:
    - pytest-embedded dut
    - tiny-test-fw dut
    - ATS UartPort
    - SerialDut
    - serial.Serial: will be converted to SerialDut, please do not read
    - Other dut objects that matched ``BaseDut``.

    More

    Args:
        dut (Any): the dut object from other frameworks

    Returns:
        DutWrapper: _description_
    """
    return DutWrapper(dut)
