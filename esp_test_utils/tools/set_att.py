import argparse
import logging

try:
    # Run from `python -m esp_test_utils.tools.set_att`
    from ..devices import attenuator
except ImportError:
    from esp_test_utils.devices import attenuator

ALL_ATT_TYPES = [t.value for t in attenuator.AttType]


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(
        description='Set Attenuator',
    )
    parser.add_argument('-v', '--att_value', type=float, required=True, help='att value to set')
    parser.add_argument('-p', '--port', type=str, help='att device path or usb port, eg: /dev/ttyUSB0, 1-5.1')
    parser.add_argument('--type', type=str, help='att device type', choices=ALL_ATT_TYPES)
    args = parser.parse_args()

    att_dev = attenuator.find_att_dev(args.port, args.type)
    res = att_dev.set_att(args.att_value)
    logging.info(f'Set att {args.att_value} result: {res}')
