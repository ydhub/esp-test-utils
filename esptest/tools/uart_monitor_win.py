"""Windows UART port monitor (polling-based).

pyudev / fcntl are Linux-only, so Windows uses a separate entry that polls
``serial.tools.list_ports`` instead of udev netlink events. Shared display and
chip-detect logic lives in :mod:`esptest.tools.uart_monitor`.
"""

import time

from . import uart_monitor


def start_monitoring() -> None:
    """Poll serial ports periodically and refresh the on-screen table."""
    uart_monitor._bootstrap_monitoring()  # pylint: disable=protected-access

    try:
        while True:
            uart_monitor.check_new_devices_status()
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main() -> None:
    start_monitoring()


if __name__ == '__main__':
    main()
