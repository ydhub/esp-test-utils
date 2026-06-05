import argparse
import json

try:
    # Run from `python -m esptest.scripts.tempbox`
    from ..devices.tempbox import TempboxController, get_tempbox_port
except ImportError:
    from esptest.devices.tempbox import TempboxController, get_tempbox_port


def main() -> None:
    parser = argparse.ArgumentParser(description='U680 tempbox controller')
    parser.add_argument('--port', default=None, help='Serial port. Empty means auto-detect.')
    parser.add_argument('--address', type=int, default=1, help='Modbus slave address')
    parser.add_argument('--mode', choices=['program', 'custom', 'read', 'stop'], default='read')
    parser.add_argument('--program', type=int, default=1, help='Program number for program mode')
    parser.add_argument('--temp', type=float, default=25.0, help='Target temp for custom mode')
    args = parser.parse_args()

    port = get_tempbox_port(args.port)
    if not port:
        raise ValueError('No tempbox serial port found')

    ctrl = TempboxController(port=port, address=args.address)
    try:
        if args.mode == 'program':
            ctrl.start_program_test(args.program)
            print(json.dumps({'mode': 'program', 'program': args.program, 'port': port}, ensure_ascii=False))
        elif args.mode == 'custom':
            ctrl.start_custom_test(args.temp)
            print(json.dumps({'mode': 'custom', 'temp': args.temp, 'port': port}, ensure_ascii=False))
        elif args.mode == 'stop':
            ctrl.stop_current_job()
            print(json.dumps({'mode': 'stop', 'port': port}, ensure_ascii=False))
        status = ctrl.read_realtime()
        print(json.dumps(status, ensure_ascii=False))
    finally:
        ctrl.close()


if __name__ == '__main__':
    main()
