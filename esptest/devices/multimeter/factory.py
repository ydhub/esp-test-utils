"""Draft: Multimeter discovery and selection helpers."""

import esptest.common.compat_typing as t

from .base import DeviceInfo, get_backend_class, registered_backends
from .facade import Multimeter


def list_multimeters(
    backend: t.Optional[str] = None,
    address: t.Optional[int] = None,
    resource: t.Optional[str] = None,
    serial_number: t.Optional[str] = None,
    path: t.Optional[str] = None,
) -> t.List[DeviceInfo]:
    """Draft: List matching multimeters; infer backend only when unambiguous."""
    filters = {}  # type: t.Dict[str, t.Any]
    if address is not None:
        filters['address'] = address
    if resource is not None:
        filters['resource'] = resource
    if serial_number is not None:
        filters['serial_number'] = serial_number
    if path is not None:
        filters['path'] = path

    if backend is not None:
        backend_cls = get_backend_class(backend)
        return backend_cls.list_devices(**filters)

    found = []  # type: t.List[t.Tuple[str, t.List[DeviceInfo]]]
    for name, backend_cls in list(registered_backends().items()):
        try:
            devices = backend_cls.list_devices(**filters)
        except NotImplementedError:
            continue
        if devices:
            found.append((name, devices))

    if len(found) == 1:
        return found[0][1]
    if len(found) == 0:
        return []
    names = ', '.join(item[0] for item in found)
    raise RuntimeError(f'multiple backends returned devices ({names}); pass backend= explicitly')


def get_multimeter_specific(
    backend: t.Optional[str] = None,
    address: t.Optional[int] = None,
    resource: t.Optional[str] = None,
    serial_number: t.Optional[str] = None,
    path: t.Optional[str] = None,
) -> Multimeter:
    """Draft: Return Multimeter for exactly one match; else RuntimeError."""
    infos = list_multimeters(
        backend=backend,
        address=address,
        resource=resource,
        serial_number=serial_number,
        path=path,
    )
    if len(infos) != 1:
        raise RuntimeError(f'expected exactly one multimeter match, got {len(infos)}')
    info = infos[0]
    return Multimeter(
        backend=info.backend,
        address=info.address,
        resource=info.resource,
    )
