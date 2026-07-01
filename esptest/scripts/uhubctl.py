import argparse
import logging
import sys
from pathlib import Path

try:
    # Run from `python -m esptest.scripts.uhubctl`
    from ..devices.usb_hub import HUB_ACTIONS, UsbHubControl, UsbHubError, parse_hub_and_port
    from ..devices.usb_topology import DEFAULT_SYSFS, format_tree, monitor_usb, scan_usb
except ImportError:
    from esptest.devices.usb_hub import HUB_ACTIONS, UsbHubControl, UsbHubError, parse_hub_and_port
    from esptest.devices.usb_topology import DEFAULT_SYSFS, format_tree, monitor_usb, scan_usb

# Power actions need a -p/--port target; topology actions do not.
POWER_ACTIONS = list(HUB_ACTIONS) + ['status', 'reset']
TOPOLOGY_ACTIONS = ['ls', 'monitor']


def _run_power_action(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.hub:
        if not args.port:
            parser.error('--port (bare port number) is required when --hub is given')
        hub, port = args.hub, args.port
    else:
        if not args.port:
            parser.error('--port is required (USB location like 1-6.1.2)')
        hub, port = parse_hub_and_port(args.port)

    ctrl = UsbHubControl(timeout=args.timeout, sudo=args.sudo)

    if args.action == 'status':
        status = ctrl.get_port_status(hub, port)
        print(status.line.strip())
        print(f'power={status.power_on} device={status.has_device}')
        return

    if args.action == 'reset':
        out = ctrl.smart_reset(hub, port)
        if out is None:
            print('SKIPPED (device already enumerated)')
        else:
            print(out.strip())
        return

    out = ctrl.set_power(hub, port, args.action)
    print(out.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description='Control and inspect USB hubs via uhubctl / sysfs')
    parser.add_argument(
        'action',
        choices=POWER_ACTIONS + TOPOLOGY_ACTIONS,
        help=(
            'off/on/cycle/toggle: set port power; '
            'status: show port status; '
            'reset: power-cycle only if no device is enumerated; '
            'ls: print the USB topology tree; '
            'monitor: watch for USB plug/unplug events'
        ),
    )
    parser.add_argument(
        '-p',
        '--port',
        type=str,
        help='USB location, eg: 1-6.1.2 (hub+port auto-split). With --hub, pass the bare port number.',
    )
    parser.add_argument('--hub', type=str, help='Raw uhubctl hub location, eg: 1-6.1 (requires --port)')
    parser.add_argument('--timeout', type=float, default=15, help='uhubctl timeout in seconds')
    parser.add_argument('--sudo', action='store_true', help='run uhubctl with sudo')
    # topology options (ls / monitor)
    parser.add_argument('-a', '--all', action='store_true', help='ls: also show empty hub ports')
    parser.add_argument('--interval', type=float, default=1.0, help='monitor: poll interval in seconds')
    parser.add_argument('--sysfs', type=Path, default=DEFAULT_SYSFS, help='USB sysfs directory')
    args = parser.parse_args()

    if args.action == 'ls':
        snapshot = scan_usb(args.sysfs)
        print(format_tree(snapshot, show_empty=args.all))
        if snapshot.errors and not snapshot.devices:
            sys.exit(1)
        return

    if args.action == 'monitor':
        print(f'monitoring USB changes on {args.sysfs} (every {args.interval:g}s, Ctrl-C to stop)')
        try:
            monitor_usb(args.sysfs, interval=args.interval)
        except KeyboardInterrupt:
            print('\nstopped')
        return

    _run_power_action(args, parser)


def cli() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        main()
    except (UsbHubError, ValueError) as e:
        logging.error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    cli()
