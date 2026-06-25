import json
import logging
import argparse
import sys
from dataclasses import asdict

try:
    # Run from `python -m esptest.scripts.list_ports`
    from ..devices.esp_serial import list_all_esp_ports
except ImportError:
    from esptest.devices.esp_serial import list_all_esp_ports


def run_uart_monitor() -> None:
    try:
        from esptest.tools.uart_monitor import start_monitoring
    except ImportError as e:
        print(f'import uart_monitor failed: {str(e)}`')
        sys.exit(1)
    start_monitoring()


def main() -> None:
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--monitor', action='store_true', help='run uart port monitor')
    parser.add_argument('--format', type=str, default='text', help='output format: text, json')
    args = parser.parse_args()

    if args.monitor:
        run_uart_monitor()
        return

    if args.format == 'json':
        data = []
        for port in list_all_esp_ports():
            data.append(asdict(port))
        print(json.dumps(data, indent=4))
        return

    print('All devices:')
    print('Device           Location     target  version xtal mac                 description')
    for port in list_all_esp_ports():
        if port.support_esptool:
            print(f'{port.device:16s} {port.location:12s} {port.target:8s} {port.chip_version:8s} {port.mac:20s} {port.chip_description}  {str(port)}')
        else:
            print(f'{port.device:16s} {port.location:12s}  -----  {port.serial_description} [esptool not supported]')


if __name__ == '__main__':
    main()
