import argparse
import logging
import os
import re

from esptest.devices.serial_tools import get_all_serial_ports
from esptest.tools.download_bin import download_bin_to_ports


def main() -> None:
    parser = argparse.ArgumentParser(description='Download bin')
    parser.add_argument('bin_path', type=str, nargs='?', help='esp bin path, default ./build')
    parser.add_argument('-p', '--ports', type=str, nargs='*', help='download port list')
    parser.add_argument(
        '--range', type=str, help='port list from range (linux), eg: "0-10" equals to "-p ttyUSB0 ttyUSB1 ... ttyUSB10"'
    )
    parser.add_argument('--all', action='store_true', help='download to all serial ports.')
    parser.add_argument('--erase-nvs', type=bool, default=True, help='use --erase-nvs=n to skip erase nvs')
    parser.add_argument('--max-workers', type=int, default=True, help='max download threads')
    args = parser.parse_args()

    bin_path = args.bin_path or './build'
    if not os.path.isdir(bin_path):
        raise ValueError(f'Can not find bin_path: {bin_path}')

    ports = []
    if args.ports:
        ports = args.ports
    elif args.range:
        match = re.match(r'(\d+)-(\d+)', args.range)
        assert match
        start, end = map(int, match.groups())
        ports = [f'ttyUSB{i}' for i in range(start, end + 1)]
    elif args.all:
        ports = [p.device for p in get_all_serial_ports()]
    else:
        ports = [os.getenv('ESPPORT') or '/dev/ttyUSB0']
    assert isinstance(ports, list)

    logging.critical(f'Download {bin_path} to {ports}')
    download_bin_to_ports(bin_path, ports, args.erase_nvs, args.max_workers)


if __name__ == '__main__':
    main()
