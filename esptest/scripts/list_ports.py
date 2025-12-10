import argparse
import sys

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
    args = parser.parse_args()

    if args.monitor:
        run_uart_monitor()
        return

    print('All devices:')
    print('Device,        Location,    esptool,   target,   description')
    for port in list_all_esp_ports():
        desc = port.chip_description if port.support_esptool else port.serial_description
        print(f'{port.device:>10s},  {port.location:12s},  {port.support_esptool},   {port.target:8s},  {desc:30s}')


if __name__ == '__main__':
    main()
