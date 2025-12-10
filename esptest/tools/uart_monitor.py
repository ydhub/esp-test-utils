import asyncio
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Dict, List

import pyudev
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text
from serial.tools import list_ports

CHIP_NAME_PATTERN = re.compile(r'Chip is ([\w\- ]+).*\(revision (v[\d\.]+)\)')
CHIP_NAME_PATTERN_NEW = re.compile(r'Chip type:\s+([\w\- ]+).+\(revision (v[\d\.]+)\)')
CHIP_XTAL_PATTERN = re.compile(r'Crystal is ([\w\-]+)')
CHIP_XTAL_PATTERN_NEW = re.compile(r'Crystal frequency:\s+([\w\-]+)')
CHIP_MAC_PATTERN = re.compile(r'MAC:\s+([a-fA-F0-9:]+)')
CHIP_FLASH_PATTERN = re.compile(r'Detected flash size: (\d+\w+)')
WORKER_NUM = 4
MAX_RECENT_DEVICES = 5
MAX_DETECT_RETRY = 4


# Debug mode: set UART_MONITOR_DEBUG=1 to keep screen history and show debug logs.
DEBUG = os.environ.get('UART_MONITOR_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')


def debug_print(*args, **kwargs):  # type: ignore
    """Print debug message to stderr when debug mode is enabled."""
    if not DEBUG:
        return
    print('[DEBUG]', *args, **kwargs, flush=True)


@dataclass
class Chip:
    name: str = ''
    mac: str = ''
    revision: str = ''
    xtal: str = ''
    flash: str = ''

    def clear(self) -> None:
        self.name = ''
        self.mac = ''
        self.revision = ''
        self.xtal = ''
        self.flash = ''


@dataclass
class Device:
    location: str
    sys_device: str
    name: str
    connected: bool
    last_seen: float
    first_seen: float
    chip: Chip


console = Console()
devices: Dict[str, Device] = {}
devices_lock = threading.Lock()
detect_queue: Queue[Device] = Queue()
recent_devices: List[Device] = []  # recent connecting devices


async def detect_chip(device: Device) -> None:
    """Detect the espressif chip on specified serial port."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'lsof', device.sys_device, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        if proc.returncode == 0:
            device.chip.name = ''
            return  # lsof got succ, the device is occupied
    except FileNotFoundError:
        debug_print('lsof command not available: apt-get install lsof', file=sys.stderr)
        device.chip.name = ''
        return

    retry = MAX_DETECT_RETRY
    try:
        while True:
            proc = await asyncio.create_subprocess_exec(
                'esptool.py',
                '-p',
                device.sys_device,
                'flash_id',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode('utf8')
            debug_print(output)

            m = CHIP_NAME_PATTERN.search(output)
            if m:
                device.chip.name = m.group(1)
                device.chip.revision = m.group(2)
            elif m := CHIP_NAME_PATTERN_NEW.search(output):
                device.chip.name = m.group(1)
                device.chip.revision = m.group(2)
            m = CHIP_XTAL_PATTERN.search(output)
            if m:
                device.chip.xtal = m.group(1)
            elif m := CHIP_XTAL_PATTERN_NEW.search(output):
                device.chip.xtal = m.group(1)
            m = CHIP_MAC_PATTERN.search(output)
            if m:
                device.chip.mac = m.group(1)
            m = CHIP_FLASH_PATTERN.search(output)
            if m:
                device.chip.flash = m.group(1)

            if device.chip.name:
                break
            if 'busy' in output:
                if retry > 0:
                    retry -= 1
                    await asyncio.sleep(1 * (MAX_DETECT_RETRY - retry))
                    continue
            # not an esp32 device or other error types
            break
    except FileNotFoundError:
        debug_print('esptool command not available: pip install esptool', file=sys.stderr)
        device.chip.name = ''


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
                        device.chip.name = 'Detecting...'
                        # the device name and location may change, so we update it
                        device.sys_device = port.device
                        device.location = port.location
                        detect_queue.put(device)
                        if not initial:
                            recent_devices.append(device)

                    device.name = name
                    device.connected = True
                    device.last_seen = timestamp
                else:
                    # new device
                    device = Device(port.location, port.device, name, True, timestamp, timestamp, Chip('Detecting...'))
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


def display_serial_ports() -> None:
    table = Table(title='Serial Ports', header_style='', box=box.ROUNDED)
    table.add_column('Location', justify='left', min_width=15)
    table.add_column('Name', justify='left', min_width=10)
    table.add_column('Status', justify='center')
    table.add_column('Chip', justify='left', min_width=15)
    table.add_column('Revision', justify='left')
    table.add_column('XTAL', justify='left')
    table.add_column('MAC', justify='left', min_width=25)
    table.add_column('Flash', justify='left')

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
            chip = Text(device.chip.name, style=style)
            rev = Text(device.chip.revision, style=style)
            xtal = Text(device.chip.xtal, style=style)
            mac = Text(device.chip.mac, style=style)
            flash = Text(device.chip.flash, style=style)

            table.add_row(
                location_text,
                name_text,
                status_text,
                chip,
                rev,
                xtal,
                mac,
                flash,
                end_section=(i == len(sorted_devices) - 1),
            )

        if recent_devices:
            for device in recent_devices[::-1]:
                if (current_time - device.first_seen) <= 1800:
                    location_text = Text(device.location)
                    name_text = Text(device.name)
                    status_text = Text('●', style='green')
                    chip = Text(device.chip.name)
                    rev = Text(device.chip.revision)
                    xtal = Text(device.chip.xtal)
                    mac = Text(device.chip.mac)
                    flash = Text(device.chip.flash)
                    table.add_row(location_text, name_text, status_text, chip, rev, xtal, mac, flash)

    # In debug mode, do not clear the screen so previous debug prints are kept.
    if not DEBUG:
        console.clear()
    console.print(table)
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
