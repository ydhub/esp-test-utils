from typing import Any, List

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self


from ..adapter.dut import DutPort
from ..config import EnvConfig


class BaseEnv:
    def __init__(
        self,
        tag: str,
        config_file: str,
    ):
        self.tag = tag
        if not config_file:
            self.env_config = EnvConfig(tag)
        else:
            self.env_config = EnvConfig(tag, config_file=config_file)
        self._dut_list: List[DutPort] = []

    def setup(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def get_variable(self, name: str) -> Any:
        return self.env_config.get_variable(name)

    def __enter__(self) -> 'Self':
        """Support using "with" statement (automatically called setup and teardown)"""
        self.setup()
        return self

    def __exit__(self, exc_type, exc_value, trace):  # type: ignore
        """Always close the serial and clean resources before exiting."""
        self.teardown()
