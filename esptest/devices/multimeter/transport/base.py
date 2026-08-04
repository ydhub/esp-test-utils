"""Draft: GPIB transport abstract interface."""

from abc import ABC, abstractmethod


class GPIBTransport(ABC):
    """Draft: low-level GPIB write/ask/close."""

    @abstractmethod
    def write(self, cmd: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def ask(self, cmd: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
