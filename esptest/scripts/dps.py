"""Command-line control for DPS programmable power supplies."""

import argparse
from typing import Any, Dict, Optional, Sequence

try:
    from ..devices.dps import DPS, DPSError
except ImportError:  # pragma: no cover - direct script execution
    from esptest.devices.dps import DPS, DPSError


def print_status(status: Dict[str, Any]) -> None:
    print(f'model       : DPS{status["model"]} (firmware {status["version"]})')
    print(f'input       : {status["voltage_in"]:.2f} V')
    print(f'setting     : {status["voltage_set"]:.2f} V / {status["current_set"]:.3f} A')
    print(
        f'output      : {"ON" if status["output"] else "OFF"} '
        f'({status["voltage_out"]:.2f} V / {status["current_out"]:.3f} A / {status["power_out"]:.2f} W)'
    )
    print(f'mode        : {status["mode"]}')
    print(f'protection  : {status["protection"]}')
    print(f'key lock    : {"ON" if status["key_locked"] else "OFF"}')


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=('Control a DPS3005/DPS5005 over Modbus RTU. Without an action option, only print its status.')
    )
    parser.add_argument(
        '-p',
        '--port',
        help='DPS communication-board serial port. Probe all CH340 ports when omitted.',
    )
    parser.add_argument(
        '-b',
        '--baudrate',
        type=int,
        default=DPS.DEFAULT_BAUDRATE,
        help=f'Panel-configured baudrate (default: {DPS.DEFAULT_BAUDRATE}).',
    )
    parser.add_argument(
        '-a',
        '--address',
        type=int,
        default=DPS.DEFAULT_SLAVE_ADDRESS,
        help=f'Modbus slave address (default: {DPS.DEFAULT_SLAVE_ADDRESS}).',
    )
    parser.add_argument(
        '-v',
        '--voltage',
        type=float,
        help=f'Output voltage in V ({DPS.MIN_VOLTAGE} to {DPS.MAX_VOLTAGE}).',
    )
    parser.add_argument(
        '-c',
        '--current',
        type=float,
        help=f'Current limit in A ({DPS.MIN_CURRENT} to {DPS.MAX_CURRENT}).',
    )
    parser.add_argument('-o', '--output', choices=['on', 'off'], help='Switch output on or off.')
    parser.add_argument('--ovp', type=float, help='Over-voltage threshold in V.')
    parser.add_argument('--ocp', type=float, help='Over-current threshold in A.')
    parser.add_argument('--opp', type=float, help='Over-power threshold in W.')
    args = parser.parse_args(argv)

    try:
        if args.port:
            device = DPS(args.port, baudrate=args.baudrate, slave_address=args.address)
        else:
            device = DPS.auto_detect(baudrate=args.baudrate, slave_address=args.address)
            print(f'Detected {device.model_name} on {device.port}')

        with device:
            if args.ovp is not None or args.ocp is not None or args.opp is not None:
                protection = device.set_protection(
                    over_voltage=args.ovp,
                    over_current=args.ocp,
                    over_power=args.opp,
                )
                print(
                    f'protection set to {protection["over_voltage"]:.2f} V / '
                    f'{protection["over_current"]:.3f} A / {protection["over_power"]:.2f} W'
                )
            if args.voltage is not None:
                print(f'voltage set to {device.set_voltage(args.voltage):.2f} V')
            if args.current is not None:
                print(f'current set to {device.set_current(args.current):.3f} A')
            if args.output is not None:
                enabled = device.set_output(args.output == 'on')
                print(f'output switched {"ON" if enabled else "OFF"}')
            print_status(device.read_status())
        return 0
    except DPSError as e:
        print(e)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
