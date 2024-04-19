import queue
import re
import threading
import time
from typing import Any
from typing import AnyStr
from typing import Dict
from typing import Optional
from typing import Union

import pexpect.fdpexpect
import pexpect.spawnbase
import serial
from serial import Serial

from esp_test_utils.basic import generate_timestamp
from esp_test_utils.basic import to_bytes
from esp_test_utils.basic import to_str
from esp_test_utils.logger import get_logger

logger = get_logger('SerialDut')


class SerialSpawn(pexpect.spawnbase.SpawnBase):
    """Create a new class for pexpect with serial reading thread.

    There's some reason that we can not use pyserial with pexpect.fdpexpect directly:
        - pyserial do not support fileno in windows.
        - Pexpect only read from serial during expect() method.
        - Can not read more than 4K data at once, the data may be lost if it is not read in time:
        - https://stackoverflow.com/questions/2415074/serial-port-not-able-to-write-big-chunk-of-data

    """

    def __init__(
        self,
        serial_instance: serial.Serial,
        serial_log_file: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        """_summary_

        Args:
            serial_instance (serial.Serial): serial instance created by pyserial.
            serial_log_file (str, optional): log file path for saving serial output logs. Defaults to None.
            timeout (int, optional): pexpect default timeout. Defaults to 30.
        """
        super().__init__(timeout=timeout)
        self.serial = serial_instance

        self._data_cache = b''
        # Save serial logs to file
        self.serial_log_file = serial_log_file
        self._line_cache = b''
        self._last_write_time = time.time()
        # Create a new thread to read data from serial port
        self._read_queue: queue.Queue = queue.Queue()
        self._read_thread_stop_event = threading.Event()
        self._read_thread = threading.Thread(target=self._read_incoming)
        self._read_thread.daemon = True
        self._read_thread.start()

    def _write_serial_log(self, data: bytes) -> None:
        """Write serial outputs to log file"""
        data_to_write = b''
        if data:
            self._line_cache += data
            if self._line_cache.endswith(b'\n'):
                data_to_write = self._line_cache
                self._line_cache = b''
            elif b'\n' in self._line_cache:
                _index = self._line_cache.rfind(b'\n') + 1
                data_to_write = self._line_cache[:_index]
                self._line_cache = self._line_cache[_index:]
        if not data_to_write and self._line_cache and time.time() - self._last_write_time > self.serial.timeout * 3:
            # No new data for a long time, flush line cache
            # Default timeout is serial.timeout * 3, depends on read timeout of serial instance
            data_to_write = self._line_cache
            self._line_cache = b''

        if data_to_write:
            self._last_write_time = time.time()
            if self.serial_log_file:
                with open(self.serial_log_file, 'ab+') as f:
                    _time_info = f'\n[{generate_timestamp()}]\n'.encode()
                    f.write(_time_info)
                    f.write(data_to_write)
            else:
                logger.debug(f'[{self.serial.port}]: {to_str(data_to_write)}')

    def _read_incoming(self) -> None:
        """Running in a thread to read serial output and save to data cache."""
        logger.debug(f'Start serial {self.serial.port} read thread.')
        while True:
            if self._read_thread_stop_event.is_set():
                # Stop the thread when spawn stop.
                logger.debug(f'Stop serial {self.serial.port} read thread.')
                return
            new_data = b''
            try:
                new_data = self.serial.read(1024)
            except serial.SerialException as e:
                self._log(to_bytes(f'SerialException: {str(e)}'), 'read')
                self._write_serial_log(to_bytes(f'SerialException: {str(e)}'))
                logger.warning(f'{self.serial.port} reading thread stopped because of {type(e)}: {str(e)}')
                return
            if new_data:
                self._read_queue.put(new_data)
            # the last line may be cached, to make the file more readable after adding timestamp
            # always check need write to file or not whether there's new data
            self._write_serial_log(new_data)

    def write(self, data: bytes) -> None:
        self.serial.write(data)

    def read_nonblocking(self, size: int = 1, timeout: Optional[int] = None) -> bytes:
        """This method was used during expect(), reads data from serial output data cache.

        If the data cache is not empty, it will return immediately. Otherwise, waiting for new data.

        Args:
            size (int, optional): maximum size of returning data. Defaults to 1.
            timeout (int | None, optional): maximum block time waiting for new data. Defaults to None (spawn.timeout).

        Returns:
            bytes: new serial output data.
        """
        if timeout is None:
            timeout = self.timeout
        t0 = time.time()
        time_left = t0 + timeout - time.time()
        while len(self._data_cache) < size and time_left > 0:
            try:
                if self._data_cache:
                    # do non-blocking read if data cache is not empty
                    _new_data = self._read_queue.get(timeout=0)
                else:
                    _new_data = self._read_queue.get(timeout=time_left)
                self._data_cache += _new_data
            except queue.Empty:
                break
            time_left = t0 + timeout - time.time()
        if self._data_cache:
            ret_data = self._data_cache[:size]
            self._data_cache = self._data_cache[size:]
        else:
            ret_data = b''
        # _log here to be same with pexpect SpawnBase
        self._log(ret_data, 'read')
        return ret_data

    def stop(self) -> None:
        """Stop and clean up"""
        logger.debug(f'Stopping SerialSpawn {self.serial.port}')
        self._read_thread_stop_event.set()
        self._read_thread.join()
        self._read_queue.empty()
        self._data_cache = b''
        self._line_cache = b''


class SerialDut:
    """A basic Dut class that supports serial port read and write

    This class using serial with pexpect.
    """

    def __init__(
        self,
        name: str,
        port: Optional[str],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.name: str = name
        self.port: Optional[str] = port

        self._serial: Optional[serial.Serial] = None
        self._serial_config: Dict[str, Any] = {}
        self._pexpect_proc: Optional[SerialSpawn] = None
        if self.port:
            self._serial = serial.Serial(port, *args, **kwargs)
            self._open_serial_port()
        else:
            # support set serial after class initialized
            self._serial = None

    def _open_serial_port(self) -> None:
        if self._serial:
            assert self.serial.timeout is not None, 'Serial port timeout must be specified!'
            self._serial_config = {
                'port': self._serial.port,
                'baudrate': self._serial.baudrate,
                'bytesize': self._serial.bytesize,
                'parity': self._serial.parity,
                'stopbits': self._serial.stopbits,
                'timeout': self._serial.timeout,
                'xonxoff': self._serial.xonxoff,
                'rtscts': self._serial.rtscts,
                'write_timeout': self._serial.write_timeout,
                'dsrdtr': self._serial.dsrdtr,
            }
            if not self._serial.is_open:
                self._serial.open()
            self._pexpect_proc = SerialSpawn(self._serial)

    @property
    def serial(self) -> Serial:
        """Get Current serial instance."""
        return self._serial

    @serial.setter
    def serial(self, serial_instance: Optional[Serial] = None) -> None:
        """Set serial instance, will close and clean up the old serial resources"""
        if self._serial:
            assert self._pexpect_proc
            self._pexpect_proc.stop()
            self._pexpect_proc = None
            if self._serial.is_open:
                self._serial.close()
        if serial_instance:
            self._serial = serial_instance
            self._open_serial_port()

    def close(self) -> None:
        """Close serial port and clean up resources."""
        self.serial = None

    def reopen(self) -> None:
        """Open the same serial port again and enable serial read thread."""
        self.serial = serial.Serial(self._serial_config)

    def set_serial_log_file(self, log_file: str) -> None:
        """Save all serial logs to a file, default using logging.DEBUG if log_file is not set

        Args:
            log_file (str): serial log file path
        """
        assert self._pexpect_proc
        with open(log_file, 'ab+') as f:
            f.write(f'----------- Saving {self.name}:{self.serial.port} logs to this file ----------\n'.encode())
        self._pexpect_proc.serial_log_file = log_file

    def write(self, data: AnyStr) -> None:
        assert self._pexpect_proc, 'serial port is not set or not opened'
        raw_data = to_bytes(data)
        self._pexpect_proc.write(raw_data)

    def write_line(self, data: str) -> None:
        data = to_bytes(data, ending='\r\n')
        return self.write(data)

    def expect_exact(self, pattern: Union[str, bytes], timeout: int = 30) -> None:
        """this is similar to expect(), but only uses plain string/bytes matching"""
        assert self._pexpect_proc, 'serial port is not set or not opened'
        pexpect_pattern = to_bytes(pattern)
        self._pexpect_proc.expect_exact(pexpect_pattern, timeout=timeout)

    def expect(self, pattern: Union[str, bytes, re.Pattern], timeout: int = 30) -> Optional[re.Match]:
        """This seeks through the stream until a pattern is matched.

        This expect() method is different with the one in pexpect.
        This method only accepts pattern type str/bytes or re.Pattern. Does not accept list, EOF or TIMEOUT.
        If the pattern type is str or bytes, this method is similar to expect_exact(), but returning None.
        If the pattern type is re.Pattern, this method will return a re.Match object if the pattern is matched.

        Args:
            pattern (Union[str, bytes, re.Pattern]): pattern to match
            timeout (int, optional): seconds of waiting for new data if match failed. Defaults to 30s.

        Returns:
            Optional[re.Match]: match result if the input pattern is re.Pattern
        """
        assert self._pexpect_proc, 'serial port is not set or not opened'
        if isinstance(pattern, (bytes, str)):
            self.expect_exact(pattern, timeout=timeout)
            return None

        assert isinstance(pattern, re.Pattern)
        if isinstance(pattern.pattern, str):
            # re-compile regex pattern using bytes
            pexpect_pattern = re.compile(to_bytes(pattern.pattern))
        else:
            pexpect_pattern = pattern
        self._pexpect_proc.expect(pexpect_pattern, timeout=timeout)
        match = self._pexpect_proc.match
        if isinstance(pattern.pattern, str):
            # convert the match result into string
            match = pattern.match(to_str(match.group(0)))
        return match  # type: ignore

    def __enter__(self) -> 'SerialDut':
        """Support using `with` statement"""
        return self

    def __exit__(self, exc_type, exc_value, trace):  # type: ignore
        """Always close the serial and clean resources before exiting."""
        self.close()
