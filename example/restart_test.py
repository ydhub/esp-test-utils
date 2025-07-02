import logging
import re
import sys
import time

from serial import Serial

from esptest.all import dut_wrapper


def test_restart() -> None:
    ser = Serial('/dev/ttyUSB0', 115200, timeout=0.01)
    with dut_wrapper(ser, 'DUT', './dut_logs/dut.log') as test_dut:
        try:
            test_dut.flush_data()
            test_dut.write('restart\r\n')
            match = test_dut.expect(re.compile(r'Loaded app from partition at offset (0x\w+)[^\w]'), timeout=5)
            test_dut.expect('main_task: Returned from app_main', timeout=5)
            logging.critical(f'BOOT Offset: {match.group(1)}')
            time.sleep(0.1)
        except TimeoutError as e:
            logging.error(str(e))
            dut_data = test_dut.read_all_bytes()
            logging.critical(f'dut data: {dut_data}')  # type: ignore
            sys.exit(1)


if __name__ == '__main__':
    test_restart()
