import asyncio
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from queue import Queue
from typing import Deque, Dict, List

import pyudev
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text
import serial
from serial.tools import list_ports

from ..devices.esp_serial import EspPortInfo, detect_port_info_no_cache

MAX_RECENT_DEVICES = 5
MAX_DETECT_RETRY = 2
MAX_DEBUG_LOGS = 20

# Debug mode: set UART_MONITOR_DEBUG=1 to keep screen history and show debug logs.
DEBUG = os.environ.get('UART_MONITOR_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')


@dataclass
class Chip:
    target: str = ''
    mac: str = ''
    revision: str = ''
    xtal: str = ''
    flash: str = ''
    description: str = ''

    def clear(self) -> None:
        self.target = ''
        self.mac = ''
        self.revision = ''
        self.xtal = ''
        self.flash = ''
        self.description = ''


@dataclass
class Device:
    name: str
    sys_device: str
    location: str
    description: str
    connected: bool
    last_seen: float
    first_seen: float
    chip: Chip


console = Console()
devices: Dict[str, Device] = {}
devices_lock = threading.Lock()
detect_queue: Queue[Device] = Queue()
recent_devices: List[Device] = []  # recent connecting devices
debug_logs: Deque[str] = deque(maxlen=MAX_DEBUG_LOGS)
debug_logs_lock = threading.Lock()


def debug_print(*args, **kwargs) -> None:  # type: ignore
    """Record debug message for on-screen debug log panel."""
    if not DEBUG:
        return
    with debug_logs_lock:
        debug_logs.append('[DEBUG] ' + ' '.join(str(arg) for arg in args))


def _update_chip_from_port_info(chip: Chip, esp_port: EspPortInfo) -> bool:
    if not esp_port.support_esptool:
        chip.clear()
        chip.target = 'unknown'
        chip.description = esp_port.serial_description
        return True
    chip.target = esp_port.target
    chip.revision = esp_port.chip_version
    chip.xtal = f'{esp_port.chip_xtal}MHz' if esp_port.chip_xtal else ''
    chip.mac = esp_port.mac
    chip.flash = esp_port.flash_size or ''
    chip.description = esp_port.chip_description
    return True


async def detect_port_chip(device: Device) -> None:
    """Detect chip info on a serial port with retry."""
    retry = MAX_DETECT_RETRY
    while True:
        esp_port_info = None
        try:
            esp_port_info = await asyncio.to_thread(
                detect_port_info_no_cache,
                device.sys_device,
                device.location,
                device.description,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            debug_print(f'{device.sys_device} detect info failed {type(e)}: {str(e)}')

        debug_print(esp_port_info)
        if esp_port_info:
            _update_chip_from_port_info(device.chip, esp_port_info)
            if esp_port_info.support_esptool:
                return

        # retry if esptool failed
        if retry > 0:
            retry -= 1
            await asyncio.sleep(1 * (MAX_DETECT_RETRY - retry))
            continue
        return


async def detect_chip(device: Device) -> None:
    """Detect the espressif chip on specified serial port."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'lsof', device.sys_device, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        if proc.returncode == 0:
            debug_print(f'{device.sys_device} is occupied (lsof)')
            device.chip.target = ''
            return  # lsof got succ, the device is occupied
    except FileNotFoundError:
        debug_print('lsof command not available: apt-get install lsof')
        device.chip.target = ''
        return

    await detect_port_chip(device)


async def detect_all_chips() -> None:
    """Detect all devices concurrently."""
    tasks = [detect_chip(detect_queue.get()) for _ in range(detect_queue.qsize())]
    await asyncio.gather(*tasks, return_exceptions=False)


def detect_chip_worker() -> None:
    while True:
        device = detect_queue.get()
        asyncio.run(detect_chip(device))
        display_serial_ports()


def refresh_serial_ports(initial: bool = True) -> bool:
    global recent_devices  # pylint: disable=global-statement
    timestamp = time.time()
    changed = False

    with devices_lock:
        ports = list(list_ports.comports())
        for port in ports:
            iface_path = port.usb_interface_path
            if port.location and iface_path:
                name = port.name if port.name else port.device.split('/')[-1]
                if iface_path in devices:
                    # update the device info
                    device = devices[iface_path]
                    if device.last_seen - device.first_seen < 10 and timestamp - device.first_seen >= 10:  # pylint: disable=chained-comparison
                        changed = True

                    if not device.connected:
                        changed = True
                        device.first_seen = timestamp
                        device.chip.clear()
                        device.chip.target = 'Detecting...'
                        # the device name and location may change, so we update it
                        device.sys_device = port.device
                        device.location = port.location
                        device.description = port.description
                        detect_queue.put(device)
                        if not initial:
                            recent_devices.append(device)

                    device.name = name
                    device.connected = True
                    device.last_seen = timestamp
                else:
                    # new device
                    device = Device(
                        name,
                        port.device,
                        port.location,
                        port.description,
                        connected=True,
                        last_seen=timestamp,
                        first_seen=timestamp,
                        chip=Chip(target='Detecting...'),
                    )
                    devices[iface_path] = device
                    detect_queue.put(device)
                    if not initial:
                        recent_devices.append(device)
                    changed = True

        # update the status of disconnected devices
        disconnect_devices = set()
        for iface_path, device in list(devices.items()):
            if device.last_seen < timestamp:
                if device.connected:
                    device.connected = False
                    disconnect_devices.add(device.location)
                    changed = True
                if device.last_seen < timestamp - 10:
                    del devices[iface_path]
                    changed = True

        recent_devices = [
            d
            for d in recent_devices[-MAX_RECENT_DEVICES:]
            if d.location not in disconnect_devices and (timestamp - d.last_seen) <= 1800
        ]
    return changed


def device_event_handler(action, device):  # type: ignore  # pylint: disable=unused-argument
    if device.subsystem != 'tty':
        return
    if refresh_serial_ports(False):
        display_serial_ports()


def check_new_devices_status() -> None:
    if refresh_serial_ports(False):
        display_serial_ports()


def _add_debug_logs_row() -> None:
    if not DEBUG:
        return
    with debug_logs_lock:
        logs = list(debug_logs)
    log_table = Table(title='Debug Logs', header_style='', box=box.ROUNDED, show_header=False)
    log_table.add_column('Message', overflow='fold')
    if logs:
        for line in logs:
            log_table.add_row(Text(line, style='dim'))
    else:
        log_table.add_row(Text('(no logs yet)', style='dim italic'))
    console.print(log_table)

def display_serial_ports() -> None:
    table = Table(title='Serial Ports', header_style='', box=box.ROUNDED)
    table.add_column('Location', justify='left', min_width=15)
    table.add_column('Name', justify='left', min_width=10)
    table.add_column('Status', justify='center')
    table.add_column('Target', justify='left', min_width=15)
    table.add_column('Revision', justify='left')
    table.add_column('XTAL', justify='left')
    table.add_column('MAC', justify='left', min_width=25)
    table.add_column('Flash', justify='left')
    table.add_column('Description', justify='left')

    with devices_lock:
        sorted_devices = sorted(devices.values(), key=lambda d: d.location)
        current_time = time.time()

        for i, device in enumerate(sorted_devices):
            is_new_device = (current_time - device.first_seen) <= 10

            if device.connected:
                status = '●'
                style = 'green' if is_new_device else ''
                status_text = Text(status, style='green')
            else:
                status = '○'
                style = 'dim'
                status_text = Text(status, style=style)

            location_text = Text(device.location, style=style)
            name_text = Text(device.name, style=style)
            target = Text(device.chip.target, style=style)
            rev = Text(device.chip.revision, style=style)
            xtal = Text(device.chip.xtal, style=style)
            mac = Text(device.chip.mac, style=style)
            flash = Text(device.chip.flash, style=style)
            description = Text(device.chip.description, style=style)

            table.add_row(
                location_text,
                name_text,
                status_text,
                target,
                rev,
                xtal,
                mac,
                flash,
                description,
                end_section=(i == len(sorted_devices) - 1),
            )

        if recent_devices:
            for device in recent_devices[::-1]:
                if (current_time - device.first_seen) <= 1800:
                    location_text = Text(device.location)
                    name_text = Text(device.name)
                    status_text = Text('●', style='green')
                    target = Text(device.chip.target)
                    rev = Text(device.chip.revision)
                    xtal = Text(device.chip.xtal)
                    mac = Text(device.chip.mac)
                    flash = Text(device.chip.flash)
                    description = Text(device.chip.description)
                    table.add_row(
                        location_text, name_text, status_text, target, rev, xtal, mac, flash, description
                    )

    console.clear()
    console.print(table)
    _add_debug_logs_row()
    console.print('Press Ctrl+C to exit')


def start_monitoring() -> None:
    refresh_serial_ports()
    display_serial_ports()

    # detecting all ports first
    asyncio.run(detect_all_chips())
    display_serial_ports()

    # start a detect worker for new coming device
    detect_thread = threading.Thread(target=detect_chip_worker, daemon=True)
    detect_thread.start()

    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='tty')

    observer = pyudev.MonitorObserver(monitor, device_event_handler)
    observer.daemon = True
    observer.start()

    try:
        while True:
            check_new_devices_status()
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()


def main() -> None:
    start_monitoring()


if __name__ == '__main__':
    main()
