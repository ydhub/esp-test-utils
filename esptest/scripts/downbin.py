import argparse
import logging
import os
import re
import sys

from esptest.devices.serial_tools import get_all_serial_ports
from esptest.tools.download_bin import bin_path_to_dir, download_bin_to_ports


def main() -> None:
    usage_string = '%(prog)s [bin_path] [options]'
    parser = argparse.ArgumentParser(description='Download bin', usage=usage_string)
    parser.add_argument('bin_path', type=str, nargs='?', help='esp bin path, default ./build')
    parser.add_argument('-p', '--ports', type=str, nargs='*', help='download port list')
    parser.add_argument(
        '--range', type=str, help='port list from range (linux), eg: "0-10" equals to "-p ttyUSB0 ttyUSB1 ... ttyUSB10"'
    )
    parser.add_argument(
        '--all', action='store_true', help='download to all serial ports, ignored if "-p/--ports" is specified.'
    )
    parser.add_argument('--no-erase-nvs', dest='erase_nvs', action='store_false', help='skip erase nvs')
    parser.add_argument('--max-workers', type=int, default=0, help='max download threads')
    parser.add_argument('--force-no-stub', action='store_true', help='force no stub')
    parser.add_argument('--check-no-stub', action='store_true', help='check no stub')
    parser.add_argument('-v', '--verbose', action='count', default=0, help='verbose output')

    args = parser.parse_args()

    log_level = [logging.WARNING, logging.INFO, logging.DEBUG]
    logging.basicConfig(
        level=log_level[min(args.verbose, len(log_level) - 1)], format='%(asctime)s %(levelname)s %(message)s'
    )

    bin_path = args.bin_path or './build'
    if not os.path.isdir(bin_path):
        try:
            bin_path = bin_path_to_dir(bin_path)
        except Exception as e:  # pylint: disable=broad-except
            logging.exception(f'Invalid bin path {bin_path} : {str(e)}')
            sys.exit(1)

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

    try:
        download_bin_to_ports(bin_path, ports, args.erase_nvs, args.max_workers, args.force_no_stub, args.check_no_stub)
    except RuntimeError as e:
        logging.error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    main()
