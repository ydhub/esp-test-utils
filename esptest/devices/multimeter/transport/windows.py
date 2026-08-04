"""Draft: pyvisa GPIB transport (Windows / VISA)."""

import esptest.common.compat_typing as t

from .base import GPIBTransport


def _decode_reply(data: t.Union[str, bytes]) -> str:
    if isinstance(data, bytes):
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('latin-1', errors='replace')
    else:
        text = data
    return text.rstrip()


def _import_pyvisa() -> t.Any:
    try:
        import pyvisa  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError('pyvisa is required for VisaGpibTransport; install with: pip install pyvisa') from exc
    return pyvisa


def _resource_from_address(address: int) -> str:
    return f'GPIB0::{address}::INSTR'


def _first_gpib_resource(rm: t.Any) -> str:
    for name in rm.list_resources():
        if 'GPIB' in name:
            return str(name)
    raise RuntimeError('no GPIB VISA resource found')


class VisaGpibTransport(GPIBTransport):
    """Draft: GPIB via pyvisa (resource string or address)."""

    def __init__(
        self,
        resource: t.Optional[str] = None,
        address: t.Optional[int] = None,
    ) -> None:
        pyvisa_mod = _import_pyvisa()
        self._rm = pyvisa_mod.ResourceManager()
        if resource is None:
            if address is not None:
                resource = _resource_from_address(address)
            else:
                resource = _first_gpib_resource(self._rm)
        self._resource = resource
        self._device = self._rm.open_resource(resource)

    @property
    def resource(self) -> str:
        """Resolved VISA resource string."""
        return self._resource

    def write(self, cmd: str) -> None:
        self._device.write(cmd)

    def ask(self, cmd: str) -> str:
        query = getattr(self._device, 'query', None)
        if callable(query):
            raw = query(cmd)
        else:
            raw = self._device.ask(cmd)
        return _decode_reply(raw)

    def close(self) -> None:
        close = getattr(self._device, 'close', None)
        if callable(close):
            close()
        rm = getattr(self, '_rm', None)
        if rm is not None:
            rm_close = getattr(rm, 'close', None)
            if callable(rm_close):
                try:
                    rm_close()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
        self._device = None
        self._rm = None
