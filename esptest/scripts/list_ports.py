import argparse
import json
import sys
from dataclasses import asdict

try:
    # Run from `python -m esptest.scripts.list_ports`
    from ..devices.esp_serial import list_all_esp_ports
    from ..devices.serial_tools import get_all_serial_ports
except ImportError:
    from esptest.devices.esp_serial import list_all_esp_ports
    from esptest.devices.serial_tools import get_all_serial_ports


def run_uart_monitor() -> None:
    try:
        if sys.platform == 'win32':
            from esptest.tools.uart_monitor_win import start_monitoring
        else:
            from esptest.tools.uart_monitor import start_monitoring
    except ImportError as e:
        print(f'import uart_monitor failed: {str(e)}`')
        sys.exit(1)
    start_monitoring()


def main() -> None:
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--monitor', action='store_true', help='run uart port monitor')
    parser.add_argument('--format', type=str, default='text', help='output format: text, json')
    parser.add_argument(
        '--serial',
        action='store_true',
        help='list serial ports without running esptool detect, only show device, location and description',
    )
    args = parser.parse_args()

    if args.monitor:
        run_uart_monitor()
        return

    if args.serial:
        ports = get_all_serial_ports()
        if args.format == 'json':
            data = [
                {'device': port.device, 'location': port.location, 'description': port.description} for port in ports
            ]
            print(json.dumps(data, indent=4))
            return
        print('All devices:')
        print('Device           Location     description')
        for port in ports:
            print(f'{port.device:16s} {port.location or "":12s} {port.description}')
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
            print(
                f'{port.device:16s} {port.location:12s} {port.target:8s} '
                f'{port.chip_version:8s} {port.mac:20s} {port.chip_description} - {port.serial_description}'
            )
        else:
            print(f'{port.device:16s} {port.location:12s}  -----  {port.serial_description} [not esp port]')


if __name__ == '__main__':
    main()
