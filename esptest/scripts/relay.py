import argparse
import logging
import re
import subprocess
import sys
import time
from typing import Optional

import serial

from esptest.devices.serial_tools import compute_serial_port, get_all_serial_ports

# Channel 1: open / close (checksum = low 8 bits of sum of preceding bytes)
CHANNEL1_OPEN_HEX = 'A0 01 01 A2'
CHANNEL1_CLOSE_HEX = 'A0 01 00 A1'


# QinHeng CH340 serial converter (USB ID 1a86:7523)
VID_CH340 = 0x1A86
PID_CH340 = 0x7523


def get_relay_device(port: str = '') -> Optional[str]:
    if port:
        return compute_serial_port(port, strict=True)
    # find the first CH340 device
    for p in get_all_serial_ports():
        if p.vid == VID_CH340 and p.pid == PID_CH340:
            return str(p.device)
    raise ValueError('No CH340 (1a86:7523) found; connect the USB serial adapter and retry.')


def get_battery_level_pct() -> Optional[int]:
    """Run ``adb shell dumpsys battery`` and return SoC 0–100, or None on failure."""
    try:
        r = subprocess.run(
            ['adb', 'shell', 'dumpsys', 'battery'],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    m = re.search(r'level:\s*(\d+)', r.stdout, re.I)
    if not m:
        return None
    return int(m.group(1))


class RelayControl:
    def __init__(
        self,
        port: str,
        open_cmd: str = CHANNEL1_OPEN_HEX,
        close_cmd: str = CHANNEL1_CLOSE_HEX,
    ):
        self.port = get_relay_device(port)
        assert self.port, f'Failed to get relay device: {port}'
        self.open_cmd = bytes.fromhex(open_cmd)
        self.close_cmd = bytes.fromhex(close_cmd)

    def open(self) -> None:
        with serial.Serial(self.port, baudrate=9600, timeout=1) as ser:
            ser.write(self.open_cmd)
        time.sleep(0.1)

    def close(self) -> None:
        with serial.Serial(self.port, baudrate=9600, timeout=1) as ser:
            ser.write(self.close_cmd)
        time.sleep(0.1)

    def check_phone(self) -> None:
        self.open()
        time.sleep(2)
        level = get_battery_level_pct()
        if level is None:
            logging.error('adb battery: could not read level (no device or no level: in dumpsys)')
            sys.exit(1)
        if level >= 80:
            logging.info(f'battery level {level} is greater than or equal to 80, closing relay')
            self.close()
        else:
            logging.info(f'battery level {level} is less than 80, keeping relay open')


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    args = argparse.ArgumentParser(description='Relay control')
    args.add_argument('action', choices=['open', 'close', 'check-phone'], help='Action to perform')
    args.add_argument('--port', type=str, help='Serial port')
    args.add_argument('--open-cmd', type=str, default=CHANNEL1_OPEN_HEX, help='open device command')
    args.add_argument('--close-cmd', type=str, default=CHANNEL1_CLOSE_HEX, help='close device command')

    args = args.parse_args()

    relay_control = RelayControl(args.port, args.open_cmd, args.close_cmd)
    if args.action == 'open':
        relay_control.open()
    elif args.action == 'close':
        relay_control.close()
    elif args.action == 'check-phone':
        relay_control.check_phone()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.exception(f'{type(e)}: {e}')
        sys.exit(1)
