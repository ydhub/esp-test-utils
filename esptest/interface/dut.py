import typing as t
from abc import abstractmethod
from pathlib import Path

from esptool import ESPLoader

from .port import PortInterface


class DutInterface(PortInterface):
    @property
    @abstractmethod
    def dut_config(self) -> t.Any: ...

    @property
    @abstractmethod
    def target(self) -> str: ...

    # optional
    @property
    def esp(self) -> ESPLoader: ...

    @property
    @abstractmethod
    def bin_path(self) -> t.Union[str, Path]: ...

    @property
    @abstractmethod
    def sdkconfig(self) -> t.Dict[str, t.Any]: ...

    @abstractmethod
    def hard_reset(self) -> None: ...

    @abstractmethod
    def flash(self, erase_nvs: bool = True) -> None: ...

    @abstractmethod
    def flash_partition(self, part: t.Union[int, str], bin_file: str = '') -> None: ...
