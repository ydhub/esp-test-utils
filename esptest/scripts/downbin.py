import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import esptest.common.compat_typing as t
from esptest.devices.serial_tools import get_all_serial_ports
from esptest.tools.download_bin import bin_path_to_dir, bin_path_to_dir_or_bin, download_bin_to_ports
from esptest.utility.raw_flash import is_raw_bin_dir, load_raw_flash, materialize_raw_dir, write_raw_flash


def prepare_download_target(args: argparse.Namespace) -> t.Tuple[str, bool]:
    """Return (bin_path_or_dir, erase_nvs)."""
    if args.raw and args.merged:
        print('error: --raw and --merged are mutually exclusive', file=sys.stderr)
        sys.exit(2)

    bin_path = args.bin_path or './build'

    if args.raw:
        path = Path(bin_path)
        if path.is_file() and path.suffix.lower() == '.bin':
            if not args.offset or not args.chip:
                print('error: --raw bare .bin requires --offset and --chip', file=sys.stderr)
                sys.exit(2)
            return materialize_raw_dir(str(path), offset=args.offset, chip=args.chip), False

        if path.is_dir():
            if not is_raw_bin_dir(path):
                print(f'error: not a raw bin package directory: {bin_path}', file=sys.stderr)
                sys.exit(2)
            if args.offset or args.chip:
                parent = Path(tempfile.mkdtemp(prefix='raw_bin_'))
                pkg = parent / 'pkg'
                shutil.copytree(path, pkg)
                raw = load_raw_flash(path)
                write_raw_flash(
                    pkg,
                    offset=args.offset or raw['offset'],
                    chip=args.chip or raw['chip'],
                    file=str(raw['file']),
                    write_flash_args=raw.get('write_flash_args'),
                )
                return str(pkg.resolve()), False
            return str(path.resolve()), False

        print(f'error: --raw requires a .bin file or raw package directory: {bin_path}', file=sys.stderr)
        sys.exit(2)

    if args.merged:
        return bin_path_to_dir_or_bin(bin_path, allow_merged=True, check_valid=True), False

    if not os.path.isdir(bin_path):
        try:
            bin_path = bin_path_to_dir(bin_path)
        except Exception as e:  # pylint: disable=broad-except
            logging.exception(f'Invalid bin path {bin_path} : {str(e)}')
            sys.exit(1)
    return bin_path, args.erase_nvs


def main() -> None:
    usage_string = '%(prog)s [bin_path] [options]'
    parser = argparse.ArgumentParser(description='Download bin', usage=usage_string)
    parser.add_argument('bin_path', type=str, nargs='?', help='esp bin path, default ./build')
    parser.add_argument('-p', '--ports', type=str, nargs='*', help='download port list')
    parser.add_argument('-b', '--baudrate', type=int, default=0, help='download baudrate')
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
    parser.add_argument(
        '--merged',
        action='store_true',
        help='treat bin_path as a raw merged .bin (esptool merge-bin output)',
    )
    parser.add_argument('--raw', action='store_true', help='flash a raw offset-based package or bare .bin')
    parser.add_argument('--offset', type=str, default=None, help='flash offset for --raw (e.g. 0x1000)')
    parser.add_argument('--chip', type=str, default=None, help='target chip for --raw (e.g. esp32)')
    parser.add_argument('-v', '--verbose', action='count', default=0, help='verbose output')

    args = parser.parse_args()

    log_level = [logging.WARNING, logging.INFO, logging.DEBUG]
    logging.basicConfig(
        level=log_level[min(args.verbose, len(log_level) - 1)],
        format='%(asctime)s %(levelname)s %(module)s :: %(message)s',
    )

    bin_path, erase_nvs = prepare_download_target(args)

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
        download_bin_to_ports(
            bin_path,
            ports,
            erase_nvs,
            max_workers=args.max_workers,
            force_no_stub=args.force_no_stub,
            check_no_stub=args.check_no_stub,
            baud=args.baudrate,
        )
    except RuntimeError as e:
        logging.error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    main()
