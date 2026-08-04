"""Draft: linux-gpib (Gpib) transport."""

import esptest.common.compat_typing as t

from .base import GPIBTransport

_ADDR_RANGE = 31  # pads 0..30
# TODO(draft): ~80 MiB buffer for every ask() (incl. short *IDN? / pad scan).
# linux-gpib typically returns on EOI, so this is mostly wasted allocation /
# peak RSS. Prefer a small default (e.g. 256 for IDN) and a larger size only
# for FETC?/bulk reads once validated on HW.
_READ_SIZE = 8192 * 10000


def _decode_reply(data: t.Union[str, bytes]) -> str:
    if isinstance(data, bytes):
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('latin-1', errors='replace')
    else:
        text = data
    return text.rstrip()


def _import_gpib() -> t.Any:
    try:
        import Gpib  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            'linux-gpib (import Gpib) is required for LinuxGpibTransport; '
            'install the system linux-gpib package / python bindings'
        ) from exc
    return Gpib


class LinuxGpibTransport(GPIBTransport):
    """Draft: GPIB via linux-gpib ``Gpib``."""

    def __init__(self, address: t.Optional[int] = None) -> None:
        gpib_mod = _import_gpib()
        if address is None:
            address = self._find_address(gpib_mod)
        self._device = gpib_mod.Gpib(0, address)
        self._address = address

    @property
    def address(self) -> int:
        """Resolved GPIB primary address."""
        return self._address

    @staticmethod
    def _find_address(gpib_mod: t.Any) -> int:
        last_error = None  # type: t.Optional[BaseException]
        for pad in range(_ADDR_RANGE):
            inst = gpib_mod.Gpib(0, pad)
            try:
                inst.write('*IDN?')
                inst.read(100)
                return pad
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_error = exc
            finally:
                close = getattr(inst, 'close', None)
                if callable(close):
                    close()
        msg = "can't find GPIB device address (scanned pads 0..30)"
        if last_error is not None:
            raise RuntimeError(msg) from last_error
        raise RuntimeError(msg)

    def write(self, cmd: str) -> None:
        self._device.write(cmd)

    def ask(self, cmd: str) -> str:
        self._device.write(cmd)
        return _decode_reply(self._device.read(_READ_SIZE))

    def close(self) -> None:
        close = getattr(self._device, 'close', None)
        if callable(close):
            close()
