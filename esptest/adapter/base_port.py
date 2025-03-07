import abc
import functools
import logging
import os
import queue
import re
import threading
import time
from typing import AnyStr, Callable, Generic, Optional, Tuple, Type, TypeVar, Union, overload

import pexpect.spawnbase

from ..common import generate_timestamp, to_bytes, to_str
from ..logger import get_logger

try:
    from typing import Self
except ImportError:
    # ignore type hints: Self
    pass

LOGGER = get_logger('SerialDut')
NEVER_MATCHED_MAGIC_STRING = 'o6K,Q.(w+~yr~N9R'


class ExpectTimeout(TimeoutError):
    """raise same ExpectTimeout rather than different Exception from different framework"""


class RawPort(metaclass=abc.ABCMeta):
    """Define a minimum Dut class, the dut objects should at least support these methods

    the dut should at least support these attributes:
    - attribute name with type str
    - method: write_bytes() with parameters: data[bytes]
    - method: read_bytes() with parameters: timeout[float]
    """

    @classmethod
    def __subclasshook__(cls, subclass: object) -> bool:
        if not hasattr(subclass, 'read_bytes') or not callable(subclass.read_bytes):
            return False
        if not hasattr(subclass, 'write_bytes') or not callable(subclass.write_bytes):
            return False
        return True

    def write_bytes(self, data: bytes) -> None:
        """write bytes"""
        raise NotImplementedError('Port class should implement this method')

    def read_bytes(self, timeout: float = 0) -> bytes:
        """blocking read bytes"""
        raise NotImplementedError('Port class should implement this method')


T = TypeVar('T', bound=RawPort)


class PortSpawn(pexpect.spawnbase.SpawnBase, Generic[T]):
    """Create a new class for pexpect with port read()/write() method.

    There's some reason that we can not use pyserial with pexpect.fdpexpect directly:
        - pyserial do not support fileno in windows.
        - Pexpect only read from serial during expect() method.
        - Can not read more than 4K data at once, the data may be lost if it is not read in time:
        - https://stackoverflow.com/questions/2415074/serial-port-not-able-to-write-big-chunk-of-data

    """

    DEFAULT_READ_INTERVAL = 0.005

    def __init__(
        self,
        port: T,
        name: str = '',
        log_file: Optional[str] = None,
        timeout: float = 30,
        logger: logging.Logger = LOGGER,
    ) -> None:
        """PortSpawn for pexpect

        Args:
            port (RawPort): port instance with read() method.
            log_file (str, optional): log file path for saving serial output logs. Defaults to None.
            timeout (int, optional): pexpect default timeout. Defaults to 30.
            logger (logging.Logger): Specific port logger for logging.
        """
        super().__init__(timeout=timeout)
        assert isinstance(port, RawPort)
        self.name = name
        self._port = port
        if not self.name and hasattr(self.port, 'name'):
            assert isinstance(self.port.name, str)
            self.name = self.port.name
        self.logger = logger
        # Save serial logs to file
        self.log_file = log_file

        self._data_cache = b''
        self._line_cache = b''
        self._last_write_log_time = time.time()
        # Create a new thread to read data from serial port
        self._read_queue: queue.Queue = queue.Queue()
        self._read_thread_stop_event = threading.Event()
        self._read_thread = threading.Thread(target=self._read_incoming, name=f'Spawn_{self.name}')
        self._read_thread.daemon = True
        self._read_thread.start()
        self.receive_callback: Optional[Callable[[str, AnyStr], None]] = None

    @property
    def port(self) -> T:
        return self._port

    @property
    def read_timeout(self) -> float:
        if hasattr(self.port, 'read_timeout'):
            _timeout = self.port.read_timeout
            assert isinstance(_timeout, float)
            assert _timeout > 0
            return _timeout
        return self.DEFAULT_READ_INTERVAL

    @property
    def data_cache(self) -> str:
        return self._data_cache.decode('utf-8', errors='replace')

    def _write_port_log(self, data: bytes) -> None:
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
        if not data_to_write and self._line_cache and time.time() - self._last_write_log_time > self.read_timeout * 5:
            # No new data for a long time, flush line cache
            # Default timeout is serial.timeout * 5, depends on read timeout of serial instance
            # Minimum serial timeout is 1ms, 5 ms should be enough for most lines.
            data_to_write = self._line_cache
            self._line_cache = b''

        if data_to_write:
            self._last_write_log_time = time.time()
            if self.log_file:
                with open(self.log_file, 'ab+') as f:
                    _time_info = f'\n[{generate_timestamp()}]\n'.encode()
                    f.write(_time_info)
                    f.write(data_to_write)
            else:
                self.logger.debug(f'[{self.name}]: {to_str(data_to_write)}')

    def _read_incoming(self) -> None:
        """Running in a thread to read serial output and save to data cache."""
        self.logger.debug(f'Start serial {self.name} read thread.')
        assert isinstance(self.read_timeout, float)
        assert self.read_timeout > 0
        while True:
            if self._read_thread_stop_event.is_set():
                # Stop the thread when spawn stop.
                self.logger.debug(f'Stop port {self.name} read thread.')
                return
            new_data = b''
            try:
                # some port instances do not support changing read timeout, therefore use default timeout of the
                new_data = self.port.read_bytes(timeout=self.read_timeout)
            except Exception as e:  # pylint: disable=W0718
                self._log(to_bytes(f'PortRead {type(e)}: {str(e)}'), 'read')
                self._write_port_log(to_bytes(f'SerialException: {str(e)}'))
                self.logger.exception(f'{self.name} reading thread stopped {type(e)}: {str(e)}')
                return
            if new_data:
                self._read_queue.put(new_data)
                if self.receive_callback and callable(self.receive_callback):
                    # https://stackoverflow.com/questions/69732212/pylint-self-xxx-is-not-callable
                    self.receive_callback(self.name, new_data)  # pylint: disable=E1102
            # the last line may be cached, to make the file more readable after adding timestamp
            # always check need write to file or not whether there's new data
            self._write_port_log(new_data)

    def write(self, data: AnyStr) -> None:
        self.port.write_bytes(to_bytes(data))

    def read_nonblocking(self, size: int = 1, timeout: Optional[Union[int, float]] = None) -> bytes:
        """This method was used during expect(), reads data from serial output data cache.

        If the data cache is not empty, it will return immediately. Otherwise, waiting for new data.

        Args:
            size (int, optional): maximum size of returning data. Defaults to 1.
            timeout (Union[int, float] | None, optional): maximum block time waiting for new data.

        Returns:
            bytes: new serial output data.
        """
        if timeout is None:
            timeout = self.timeout
        assert timeout is not None
        t0 = time.time()
        # Read out all cache from queue first
        while True:
            try:
                _new_data = self._read_queue.get(timeout=0)
                self._data_cache += _new_data
            except queue.Empty:
                break
        self.logger.debug(self._data_cache)
        # Waiting for more data until timeout if there's no data cache.
        # Any new data should be returned immediately.
        time_left = t0 + timeout - time.time()
        while not self._data_cache and time_left > 0:
            try:
                _new_data = self._read_queue.get(timeout=time_left)
                self._data_cache += _new_data
            except queue.Empty:
                break
            time_left = t0 + timeout - time.time()
        # Returned data should not more than given size.
        if self._data_cache:
            ret_data = self._data_cache[:size]
            self._data_cache = self._data_cache[size:]
        else:
            ret_data = b''
        # _log here to be same with pexpect SpawnBase
        self._log(ret_data, 'read')  # type: ignore
        return ret_data

    def stop(self) -> None:
        """Stop and clean up"""
        self.logger.debug(f'Stopping SerialSpawn {self.name}')
        self._read_thread_stop_event.set()
        self._read_thread.join()
        self._read_queue.empty()
        self.receive_callback = None
        self._data_cache = b''
        self._line_cache = b''


class BasePort(Generic[T]):
    """A class to simply port methods for all devices / shell / sockets to similar usage

    - Create receive thread and pexpect spawn process for data read/expect
    - Redefine

    """

    EXPECT_TIMEOUT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
        TimeoutError,
        pexpect.exceptions.ExceptionPexpect,
    )
    INIT_START_PEXPECT_PROC: bool = True
    DISABLE_PEXPECT_PROC: bool = False
    PEXPECT_DEFAULT_TIMEOUT: float = 30

    def __init__(
        self,
        port: T,
        name: str = '',
        log_file: str = '',
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if port:
            assert isinstance(port, RawPort)
        self._port = port
        self._name = name
        self._log_file = log_file
        self.expect_timeout_exceptions = self.EXPECT_TIMEOUT_EXCEPTIONS
        self.logger = logger or LOGGER
        self.timeout = self.PEXPECT_DEFAULT_TIMEOUT

        self._pexpect_proc: Optional[PortSpawn] = None
        if self.INIT_START_PEXPECT_PROC:
            self.start_pexpect_proc()

    @property
    def port(self) -> T:
        return self._port  # type: ignore

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value
        if self.spawn:
            self.spawn.name = value

    def _init_log_file(self) -> None:
        if self.log_file:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, 'ab+') as f:
                f.write(f'--------- Saving {self.name}:{self.port} logs to this file --------\n'.encode())
        else:
            self.logger.debug(f'do not save {self.name}:{self.port} logs to file')

    @property
    def log_file(self) -> str:
        """Get Current dut log file."""
        if not self._log_file:
            return ''
        return os.path.abspath(self._log_file)

    @log_file.setter
    def log_file(self, new_log_file: str) -> None:
        """Set Current dut log file."""
        if new_log_file == self._log_file:
            return
        if self._pexpect_proc:
            self._pexpect_proc.serial_log_file = new_log_file
        self._log_file = new_log_file

    @property
    def spawn(self) -> Optional[PortSpawn]:
        """Allow the use of pexpect spawn enhancements, if pexpect process is available"""
        return self._pexpect_proc

    def start_pexpect_proc(self) -> None:
        if self.DISABLE_PEXPECT_PROC:
            return
        if self._pexpect_proc:
            return
        self._init_log_file()
        self._pexpect_proc = PortSpawn(self.port, self.name, self.log_file, self.PEXPECT_DEFAULT_TIMEOUT, self.logger)

    @staticmethod
    def _handle_expect_timeout(func: Callable) -> Callable:
        """Raise same type exception ExpectTimeout for ports from different frameworks"""

        @functools.wraps(func)
        def wrap(self, *args, **kwargs):  # type: ignore
            try:
                result = func(self, *args, **kwargs)
            except self.expect_timeout_exceptions as e:
                raise ExpectTimeout(str(e)) from e
            return result

        return wrap

    def write(self, data: AnyStr) -> None:
        if self._pexpect_proc:
            return self._pexpect_proc.write(data)
        raise NotImplementedError()

    def write_line(self, data: AnyStr, end: str = '\n') -> None:
        return self.write(to_bytes(data, end))

    @_handle_expect_timeout
    def expect_exact(self, pattern: Union[str, bytes], timeout: float) -> None:
        """this is similar to expect(), but only uses plain string/bytes matching"""
        if self.spawn:
            pexpect_pattern = to_bytes(pattern)
            self.spawn.expect_exact(pexpect_pattern, timeout=timeout)
        raise NotImplementedError()

    @overload
    def expect(self, pattern: str, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: bytes, timeout: float = 30) -> None: ...
    @overload
    def expect(self, pattern: re.Pattern[str], timeout: float = 30) -> re.Match[str]: ...
    @overload
    def expect(self, pattern: re.Pattern[bytes], timeout: float = 30) -> re.Match[bytes]: ...

    @_handle_expect_timeout
    def expect(self, pattern, timeout=PEXPECT_DEFAULT_TIMEOUT):  # type: ignore
        """This seeks through the stream until a pattern is matched.

        This expect() method is different with the one in pexpect.
        This method only accepts pattern type str/bytes or re.Pattern. Does not accept list, EOF or TIMEOUT.
        If the pattern type is str or bytes, this method is similar to expect_exact(), but returning None.
        If the pattern type is re.Pattern, this method will return a re.Match object if the pattern is matched.
        Can read all output data by pattern=re.compile('.+', re.DOTALL)

        Args:
            pattern (Union[str, bytes, re.Pattern]): pattern to match
            timeout (int, optional): seconds of waiting for new data if match failed. Defaults to 30s.

        Returns:
            Optional[re.Match]: match result if the input pattern is re.Pattern
        """
        if self._pexpect_proc:
            if isinstance(pattern, (bytes, str)):
                self._pexpect_proc.expect_exact(pattern, timeout=timeout)
                return None

            assert isinstance(pattern, re.Pattern)
            if isinstance(pattern.pattern, str):
                # re-compile regex pattern using bytes, with same flags
                re_flags = pattern.flags & (re.DOTALL | re.MULTILINE | re.IGNORECASE)
                pexpect_pattern = re.compile(to_bytes(pattern.pattern), re_flags)
            else:
                pexpect_pattern = pattern
            self._pexpect_proc.expect(pexpect_pattern, timeout=timeout)
            match = self._pexpect_proc.match
            if isinstance(pattern.pattern, str) and isinstance(match, re.Match):
                # convert the match result into string
                match = pattern.match(to_str(match.group(0)))
            return match  # type: ignore
        raise NotImplementedError()

    @property
    def data_cache(self) -> str:
        return self.read_all_data(flush=False)

    def flush_data(self) -> str:
        return self.read_all_data(flush=True)

    def read_all_data(self, flush: bool = True) -> str:
        return to_str(self.read_all_bytes(flush))

    def read_all_bytes(self, flush: bool = False) -> bytes:
        """Read out all data from dut, return immediately.

        Returns:
            bytes: all data read from dut
        """
        buffer = b''
        if flush:
            match = self.expect(re.compile(b'.*', re.DOTALL), timeout=0)
            assert match
            buffer = match.group(0)
        else:
            # flush spawn buffer
            assert self._pexpect_proc
            self._pexpect_proc.expect_exact(pexpect.TIMEOUT, timeout=0)
            buffer = to_bytes(self._pexpect_proc.buffer)
        assert isinstance(buffer, bytes)
        return buffer

    def close(self) -> None:
        if self._pexpect_proc:
            self._pexpect_proc.stop()

    def __enter__(self) -> 'Self':
        return self

    def __exit__(self, exc_type, exc_value, trace) -> None:  # type: ignore
        self.close()
