from pathlib import Path

from esptest.devices import usb_topology
from esptest.devices.usb_topology import (
    diff_snapshots,
    format_tree,
    parse_device_name,
    scan_usb,
)


def _write(path: Path, **fields: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, value in fields.items():
        (path / name).write_text(value + '\n')


def _build_fake_sysfs(tmp_path: Path) -> Path:
    sysfs = tmp_path / 'devices'
    sysfs.mkdir()

    # root hub usb1 with 4 ports
    _write(sysfs / 'usb1', maxchild='4', bDeviceClass='09', idVendor='1d6b', idProduct='0002', product='xHCI Host')
    # a 4-port hub on port 6 of the root
    _write(
        sysfs / '1-6',
        maxchild='4',
        bDeviceClass='09',
        idVendor='05e3',
        idProduct='0610',
        product='USB2.1 Hub',
        manufacturer='GenesysLogic',
    )
    # a CP2102 UART on 1-6.1 with a /dev/ttyUSB0 node
    _write(
        sysfs / '1-6.1',
        bDeviceClass='00',
        idVendor='10c4',
        idProduct='ea60',
        product='CP2102N USB to UART Bridge Controller',
        manufacturer='Silicon Labs',
        serial='0123ABC',
    )
    iface = sysfs / '1-6.1:1.0'
    _write(iface)
    _write(iface / 'ttyUSB0', uevent='MAJOR=188\nMINOR=0\nDEVNAME=ttyUSB0\n')
    return sysfs


def test_parse_device_name_roots_and_devices() -> None:
    assert parse_device_name('usb1') == (1, (), None)
    assert parse_device_name('1-6') == (1, (6,), 'usb1')
    assert parse_device_name('1-6.1.2') == (1, (6, 1, 2), '1-6.1')
    assert parse_device_name('not-a-device') is None


def test_scan_usb_builds_tree(tmp_path: Path) -> None:
    sysfs = _build_fake_sysfs(tmp_path)
    snap = scan_usb(sysfs)

    assert snap.errors == ()
    assert set(snap.devices) == {'usb1', '1-6', '1-6.1'}
    assert snap.roots == ['usb1']
    assert snap.children['usb1'] == ['1-6']
    assert snap.children['1-6'] == ['1-6.1']

    hub = snap.devices['1-6']
    assert hub.is_hub is True
    assert hub.port == 6
    assert hub.location == '1-6'

    uart = snap.devices['1-6.1']
    assert uart.is_hub is False
    assert uart.usb_id == '10c4:ea60'
    assert uart.tty_nodes == ('/dev/ttyUSB0',)


def test_scan_usb_missing_sysfs_returns_error(tmp_path: Path) -> None:
    snap = scan_usb(tmp_path / 'does-not-exist')
    assert snap.devices == {}
    assert snap.errors and 'does not exist' in snap.errors[0]


def test_format_tree_lists_devices(tmp_path: Path) -> None:
    sysfs = _build_fake_sysfs(tmp_path)
    tree = format_tree(scan_usb(sysfs))

    assert '[root hub] 1 xHCI Host' in tree
    assert 'port 6: 1-6 [hub]' in tree
    assert 'port 1: 1-6.1' in tree
    assert '/dev/ttyUSB0' in tree
    assert 'serial=0123ABC' in tree
    # empty ports are hidden by default
    assert '[empty]' not in tree


def test_format_tree_show_empty(tmp_path: Path) -> None:
    sysfs = _build_fake_sysfs(tmp_path)
    tree = format_tree(scan_usb(sysfs), show_empty=True)
    # root hub has 4 ports, only port 6... wait root maxchild=4 so ports 1-4 empty
    assert tree.count('[empty]') >= 1
    assert 'port 6: 1-6 [hub]' in tree
    assert 'port 1: 1-6.1' in tree


def test_diff_snapshots_detects_plug_and_unplug(tmp_path: Path) -> None:
    sysfs = _build_fake_sysfs(tmp_path)
    before = scan_usb(sysfs)

    # plug a new device on 1-6.2
    _write(
        sysfs / '1-6.2',
        bDeviceClass='00',
        idVendor='303a',
        idProduct='1001',
        product='ESP32',
    )
    after = scan_usb(sysfs)
    added, removed = diff_snapshots(before, after)
    assert added == ['1-6.2']
    assert removed == []

    # now unplug the UART
    added, removed = diff_snapshots(after, before)
    assert added == []
    assert removed == ['1-6.2']


def test_monitor_usb_invokes_callback(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sysfs = _build_fake_sysfs(tmp_path)
    events = []

    snapshots = [scan_usb(sysfs)]
    # second scan: a device appears
    _write(sysfs / '1-6.3', bDeviceClass='00', idVendor='303a', idProduct='1001', product='ESP32-S3')
    snapshots.append(scan_usb(sysfs))

    scan_calls = {'n': 0}

    def fake_scan(_sysfs: Path) -> usb_topology.UsbSnapshot:
        idx = min(scan_calls['n'], len(snapshots) - 1)
        scan_calls['n'] += 1
        return snapshots[idx]

    def fake_sleep(_seconds: float) -> None:
        if scan_calls['n'] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(usb_topology, 'scan_usb', fake_scan)
    monkeypatch.setattr(usb_topology.time, 'sleep', fake_sleep)

    try:
        usb_topology.monitor_usb(sysfs, interval=0.01, on_event=lambda action, dev: events.append((action, dev.name)))
    except KeyboardInterrupt:
        pass

    assert ('plugged', '1-6.3') in events
