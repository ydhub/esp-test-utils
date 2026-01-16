import re
from abc import ABC, abstractmethod
from typing import overload

import esptest.common.compat_typing as t

PatternLike = t.Union[str, bytes, 're.Pattern[str]', 're.Pattern[bytes]']
MatchLike = t.Union['re.Match[str]', 're.Match[bytes]', None]


class PortInterface(ABC):
    @property
    @abstractmethod
    def raw_port(self) -> t.Any: ...

    @property
    @abstractmethod
    def name(self) -> t.Any: ...

    @name.setter
    @abstractmethod
    def name(self, value: str) -> None: ...

    @abstractmethod
    def write(self, data: t.AnyStr) -> None: ...

    @abstractmethod
    def write_line(self, data: t.AnyStr, end: str = '\n') -> None: ...

    @overload
    def expect(self, pattern: str, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: bytes, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: 're.Pattern[str]', timeout: float = 30) -> 're.Match[str]': ...
    @overload
    def expect(self, pattern: 're.Pattern[bytes]', timeout: float = 30) -> 're.Match[bytes]': ...

    @abstractmethod
    def expect(self, pattern: PatternLike, timeout: float = 0) -> MatchLike: ...  # type: ignore

    @property
    @abstractmethod
    def data_cache(self) -> str: ...

    @abstractmethod
    def flush_data(self) -> str: ...

    @abstractmethod
    def read_all_data(self, flush: bool = True) -> str: ...

    @abstractmethod
    def read_all_bytes(self, flush: bool = False) -> bytes: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def __enter__(self) -> 't.Self': ...

    @abstractmethod
    def __exit__(self, exc_type, exc_value, trace) -> None: ...  # type: ignore
