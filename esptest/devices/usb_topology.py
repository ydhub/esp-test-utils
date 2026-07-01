"""Read the Linux USB topology from ``/sys/bus/usb/devices``.

This is a focused, line-based port of the topology viewer in
`huby <https://github.com/horw/huby>`_. It builds a root-hub/port/device tree
(no root privileges needed for viewing) so it can be used to:

* ``ls``      -- print the current USB tree, including the ``/dev/tty*`` nodes
  and the location string (e.g. ``1-6.1.2``) that can be fed straight into the
  ``esp-uhubctl`` power commands.
* ``monitor`` -- poll the tree and report plug/unplug events.

It is Linux specific (sysfs); on other platforms ``scan_usb`` returns an empty
snapshot with an error message.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger('devices')

DEFAULT_SYSFS = Path('/sys/bus/usb/devices')
ROOT_RE = re.compile(r'^usb(?P<bus>\d+)$')
DEVICE_RE = re.compile(r'^(?P<bus>\d+)-(?P<ports>\d+(?:\.\d+)*)$')

# bDeviceClass value for USB hubs
USB_CLASS_HUB = '09'

USB_CLASS_NAMES = {
    '00': 'Per-interface',
    '02': 'CDC',
    '03': 'HID',
    '07': 'Printer',
    '08': 'Mass Storage',
    '09': 'Hub',
    '0a': 'CDC Data',
    '0e': 'Video',
    'e0': 'Wireless',
    'ef': 'Miscellaneous',
    'ff': 'Vendor Specific',
}


def _read_text(path: Path) -> t.Optional[str]:
    try:
        value = path.read_text(errors='replace').strip()
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError):
        return None
    return value or None


def _read_int(path: Path) -> int:
    value = _read_text(path)
    if value is None:
        return 0
    try:
        return int(value, 10)
    except ValueError:
        return 0


def _read_uevent(path: Path) -> t.Dict[str, str]:
    data: t.Dict[str, str] = {}
    text = _read_text(path / 'uevent')
    if not text:
        return data
    for line in text.splitlines():
        key, sep, value = line.partition('=')
        if sep:
            data[key] = value
    return data


def _normalized_code(code: t.Optional[str]) -> t.Optional[str]:
    if not code:
        return None
    code = code.strip().lower()
    if code.startswith('0x'):
        code = code[2:]
    if len(code) == 1:
        code = f'0{code}'
    return code


def _devname_to_path(devname: t.Optional[str]) -> t.Optional[str]:
    if not devname:
        return None
    devname = devname.strip()
    if not devname:
        return None
    if devname.startswith('/dev/'):
        return devname
    return f'/dev/{devname}'


def _add_dev_node(nodes: t.List[str], devname: t.Optional[str]) -> None:
    dev_path = _devname_to_path(devname)
    if dev_path and dev_path not in nodes:
        nodes.append(dev_path)


def _collect_dev_nodes_from_tree(path: Path, nodes: t.List[str], max_depth: int = 8) -> None:
    try:
        root = path.resolve(strict=True)
    except OSError:
        return

    stack: t.List[t.Tuple[Path, int]] = [(root, 0)]
    seen: t.Set[Path] = set()
    skip_dirs = {'driver', 'subsystem', 'firmware_node', 'power'}

    while stack:
        current, depth = stack.pop()
        if current in seen:
            continue
        seen.add(current)

        _add_dev_node(nodes, _read_uevent(current).get('DEVNAME'))

        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name, reverse=True)
        except OSError:
            continue
        for child in children:
            if child.name in skip_dirs or child.is_symlink():
                continue
            try:
                if child.is_dir():
                    stack.append((child, depth + 1))
            except OSError:
                continue


def _read_dev_nodes(sysfs: Path, device_name: str, root_devname: t.Optional[str]) -> t.Tuple[str, ...]:
    nodes: t.List[str] = []
    _add_dev_node(nodes, root_devname)
    try:
        interfaces = sorted(sysfs.glob(f'{device_name}:*'), key=lambda p: p.name)
    except OSError:
        return tuple(nodes)
    for interface_path in interfaces:
        if interface_path.is_dir():
            _collect_dev_nodes_from_tree(interface_path, nodes)
    return tuple(nodes)


@dataclass
class UsbDevice:
    name: str  # sysfs name, e.g. "usb1" (root) or "1-6.1.2"
    bus: int
    port_path: t.Tuple[int, ...]
    parent_name: t.Optional[str]
    product: t.Optional[str] = None
    manufacturer: t.Optional[str] = None
    serial: t.Optional[str] = None
    id_vendor: t.Optional[str] = None
    id_product: t.Optional[str] = None
    speed: t.Optional[str] = None
    maxchild: int = 0
    device_class: t.Optional[str] = None
    dev_nodes: t.Tuple[str, ...] = ()

    @property
    def is_root(self) -> bool:
        return self.name.startswith('usb')

    @property
    def is_hub(self) -> bool:
        return self.maxchild > 0 or _normalized_code(self.device_class) == USB_CLASS_HUB

    @property
    def port(self) -> t.Optional[int]:
        if not self.port_path:
            return None
        return self.port_path[-1]

    @property
    def usb_id(self) -> t.Optional[str]:
        if self.id_vendor and self.id_product:
            return f'{self.id_vendor}:{self.id_product}'
        return None

    @property
    def location(self) -> str:
        """uhubctl-style location: root hub -> bus number, otherwise sysfs name."""
        return str(self.bus) if self.is_root else self.name

    @property
    def tty_nodes(self) -> t.Tuple[str, ...]:
        """``/dev`` nodes excluding the raw usbfs node under /dev/bus/usb."""
        return tuple(node for node in self.dev_nodes if not node.startswith('/dev/bus/usb'))

    def label(self) -> str:
        product = self.product or 'Unknown USB device'
        maker = self.manufacturer
        label = f'{maker} {product}' if maker and maker not in product else product
        if self.usb_id:
            label = f'{label} ({self.usb_id})'
        return label


@dataclass
class UsbSnapshot:
    devices: t.Dict[str, UsbDevice] = field(default_factory=dict)
    children: t.Dict[str, t.List[str]] = field(default_factory=dict)
    errors: t.Tuple[str, ...] = ()

    @property
    def roots(self) -> t.List[str]:
        return sorted(
            (name for name, dev in self.devices.items() if dev.parent_name is None),
            key=lambda name: self.devices[name].bus,
        )


def parse_device_name(name: str) -> t.Optional[t.Tuple[int, t.Tuple[int, ...], t.Optional[str]]]:
    root = ROOT_RE.match(name)
    if root:
        return int(root.group('bus')), (), None
    device = DEVICE_RE.match(name)
    if not device:
        return None
    bus = int(device.group('bus'))
    ports = tuple(int(part) for part in device.group('ports').split('.'))
    if len(ports) == 1:
        parent = f'usb{bus}'
    else:
        parent = f'{bus}-' + '.'.join(str(part) for part in ports[:-1])
    return bus, ports, parent


def _read_device(sysfs: Path, path: Path, bus: int, ports: t.Tuple[int, ...], parent: t.Optional[str]) -> UsbDevice:
    uevent = _read_uevent(path)
    dev_name = uevent.get('DEVNAME')
    return UsbDevice(
        name=path.name,
        bus=bus,
        port_path=ports,
        parent_name=parent,
        product=_read_text(path / 'product'),
        manufacturer=_read_text(path / 'manufacturer'),
        serial=_read_text(path / 'serial'),
        id_vendor=_read_text(path / 'idVendor'),
        id_product=_read_text(path / 'idProduct'),
        speed=_read_text(path / 'speed'),
        maxchild=_read_int(path / 'maxchild'),
        device_class=_read_text(path / 'bDeviceClass'),
        dev_nodes=_read_dev_nodes(sysfs, path.name, dev_name),
    )


def _sort_names(names: t.Iterable[str], devices: t.Dict[str, UsbDevice]) -> t.List[str]:
    return sorted(names, key=lambda name: (devices[name].bus, devices[name].port_path, devices[name].name))


def scan_usb(sysfs: Path = DEFAULT_SYSFS) -> UsbSnapshot:
    """Scan ``sysfs`` and return a :class:`UsbSnapshot` of the USB tree."""
    if not sysfs.exists():
        return UsbSnapshot(errors=(f'{sysfs} does not exist (USB topology is only available on Linux)',))

    try:
        entries = list(sysfs.iterdir())
    except OSError as exc:
        return UsbSnapshot(errors=(f'cannot read {sysfs}: {exc}',))

    devices: t.Dict[str, UsbDevice] = {}
    errors: t.List[str] = []
    for path in entries:
        if ':' in path.name or not path.is_dir():
            continue
        parsed = parse_device_name(path.name)
        if parsed is None:
            continue
        bus, ports, parent = parsed
        try:
            devices[path.name] = _read_device(sysfs, path, bus, ports, parent)
        except OSError as exc:
            errors.append(f'cannot read {path.name}: {exc}')

    children: t.Dict[str, t.List[str]] = {name: [] for name in devices}
    for name, device in devices.items():
        if device.parent_name and device.parent_name in devices:
            children.setdefault(device.parent_name, []).append(name)
    for parent_name, child_names in list(children.items()):
        children[parent_name] = _sort_names(child_names, devices)

    return UsbSnapshot(devices=devices, children=children, errors=tuple(errors))


def format_tree(snapshot: UsbSnapshot, show_empty: bool = False) -> str:
    """Render the snapshot as an indented tree (one line per port/device)."""
    lines: t.List[str] = []

    def render(device: UsbDevice, depth: int) -> None:
        indent = '  ' * depth
        if device.is_root:
            lines.append(f'{indent}[root hub] {device.location} {device.label()} ({device.maxchild} ports)')
        children_by_port: t.Dict[int, str] = {}
        for child_name in snapshot.children.get(device.name, []):
            child_port = snapshot.devices[child_name].port
            if child_port is not None:
                children_by_port[child_port] = child_name
        if not device.is_hub:
            return
        if show_empty and device.maxchild > 0:
            port_numbers: t.List[int] = sorted(set(range(1, device.maxchild + 1)) | set(children_by_port))
        else:
            port_numbers = sorted(children_by_port)

        for port in port_numbers:
            plugged_name = children_by_port.get(port)
            child_indent = '  ' * (depth + 1)
            if plugged_name is None:
                if show_empty:
                    lines.append(f'{child_indent}port {port}: [empty]')
                continue
            child = snapshot.devices[plugged_name]
            hub_tag = ' [hub]' if child.is_hub else ''
            extra = ''
            if child.serial:
                extra += f' serial={child.serial}'
            if child.tty_nodes:
                extra += f' {",".join(child.tty_nodes)}'
            lines.append(f'{child_indent}port {port}: {child.name}{hub_tag} {child.label()}{extra}')
            render(child, depth + 1)

    for root_name in snapshot.roots:
        render(snapshot.devices[root_name], 0)

    if snapshot.errors:
        if lines:
            lines.append('')
        lines.extend(f'error: {error}' for error in snapshot.errors)
    return '\n'.join(lines)


def diff_snapshots(old: UsbSnapshot, new: UsbSnapshot) -> t.Tuple[t.List[str], t.List[str]]:
    """Return ``(added, removed)`` device names between two snapshots."""
    old_names = set(old.devices)
    new_names = set(new.devices)
    added = _sort_names(new_names - old_names, new.devices)
    removed = _sort_names(old_names - new_names, old.devices)
    return added, removed


def monitor_usb(
    sysfs: Path = DEFAULT_SYSFS,
    interval: float = 1.0,
    on_event: t.Optional[t.Callable[[str, UsbDevice], None]] = None,
) -> None:
    """Poll the USB tree forever, invoking ``on_event(action, device)`` on changes.

    ``action`` is ``'plugged'`` or ``'unplugged'``. Runs until interrupted.
    """
    if on_event is None:
        on_event = _default_monitor_printer

    snapshot = scan_usb(sysfs)
    for error in snapshot.errors:
        logger.warning(error)
    while True:
        time.sleep(max(0.1, interval))
        new_snapshot = scan_usb(sysfs)
        added, removed = diff_snapshots(snapshot, new_snapshot)
        for name in removed:
            on_event('unplugged', snapshot.devices[name])
        for name in added:
            on_event('plugged', new_snapshot.devices[name])
        snapshot = new_snapshot


def _default_monitor_printer(action: str, device: UsbDevice) -> None:
    stamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    extra = ''
    if device.tty_nodes:
        extra = f' {",".join(device.tty_nodes)}'
    print(f'{stamp} {action:9s} {device.name} {device.label()}{extra}', flush=True)
