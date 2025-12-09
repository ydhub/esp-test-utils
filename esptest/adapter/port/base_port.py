import abc
import contextlib
import functools
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import overload

import pexpect.spawnbase

import esptest.common.compat_typing as t

from ...common import timestamp_str, to_bytes, to_str
from ...common.decorators import deprecated
from ...interface.port import PortInterface
from ...logger import get_logger

logger = get_logger('port')
NEVER_MATCHED_MAGIC_STRING = 'o6K,Q.(w+~yr~N9R'


class ExpectTimeout(TimeoutError):
    """raise same ExpectTimeout rather than different Exception from different framework"""

    def __init__(self, message: str, data_in_buffer: t.Union[str, bytes] = b'') -> None:
        super().__init__(message)
        self.data_in_buffer: t.Union[str, bytes] = data_in_buffer

    def __str__(self) -> str:
        return f'{super().__str__()}\n data_in_buffer={repr(self.data_in_buffer)}'


class RawPort(metaclass=abc.ABCMeta):
    """Define a minimum Dut class, the dut objects should at least support these methods

    the dut should at least support these attributes:
    - method: write_bytes() with parameters: data[bytes]
    - method: read_bytes() with parameters: timeout[float]

    optional attribute & method:
    - attribute: name with type str
    - attribute: read_timeout with type float
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


T = t.TypeVar('T', bound=RawPort)


@dataclass
class SpawnConfig:
    name: str = ''  # mandatory
    timeout: float = 30.0
    read_interval: float = 0
    # save rx log to log file
    log_file: t.Optional[str] = None
    # using logger.info for logs
    logger: logging.Logger = logger
    # callback  cb(data,name)
    tx_callbacks: t.Optional[t.List[t.Callable[[bytes, str], None]]] = None
    rx_callbacks: t.Optional[t.List[t.Callable[[bytes, str], None]]] = None
    # TODO: monitors


class PortSpawn(pexpect.spawnbase.SpawnBase, t.Generic[T]):
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
        raw_port: T,
        name: str = '',
        log_file: t.Optional[str] = None,
        timeout: float = 30,
        **kwargs: t.Any,
    ) -> None:
        """PortSpawn for pexpect

        Args:
            port (RawPort): port instance with read() method.
            log_file (str, optional): log file path for saving serial output logs. Defaults to None.
            timeout (int, optional): pexpect default timeout. Defaults to 30.
            logger (logging.Logger): Specific port logger for logging.
        """
        super().__init__(timeout=timeout)
        assert isinstance(raw_port, RawPort)
        self.name = name
        self._raw_port = raw_port
        if not self.name and hasattr(self.raw_port, 'name'):
            assert isinstance(self.raw_port.name, str)
            self.name = self.raw_port.name
        self.logger = kwargs.get('logger') or logger
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
        self.receive_callback: t.Optional[t.Callable[[str, t.AnyStr], None]] = None

    @property
    def raw_port(self) -> T:
        return self._raw_port

    @property
    def read_timeout(self) -> float:
        if hasattr(self.raw_port, 'read_timeout'):
            _timeout = self.raw_port.read_timeout
            assert isinstance(_timeout, (float, int))
            assert _timeout > 0
            return float(_timeout)
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
                    _time_info = f'\n[{timestamp_str()}]\n'.encode()
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
                new_data = self.raw_port.read_bytes(timeout=self.read_timeout)
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

    def write(self, data: t.AnyStr) -> None:
        self.raw_port.write_bytes(to_bytes(data))

    def read_nonblocking(self, size: int = 1, timeout: t.Optional[t.Union[int, float]] = None) -> bytes:
        """This method was used during expect(), reads data from serial output data cache.

        If the data cache is not empty, it will return immediately. Otherwise, waiting for new data.

        Args:
            size (int, optional): maximum size of returning data. Defaults to 1.
            timeout (t.Union[int, float], optional): maximum block time waiting for new data.

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
        # t.Any new data should be returned immediately.
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

    @deprecated('Should use close() for Spawn')
    def stop(self) -> None:
        self.close()

    def close(self) -> None:
        """Stop and clean up"""
        self.logger.debug(f'Stopping SerialSpawn {self.name}')
        self._read_thread_stop_event.set()
        self._read_thread.join()
        self._read_queue.empty()
        self.receive_callback = None
        self._data_cache = b''
        self._line_cache = b''


class BasePort(PortInterface, t.Generic[T]):
    """A class to simply port methods for all devices / shell / sockets to similar usage

    - Create receive thread and pexpect spawn process for data read/expect
    - Redefine

    """

    EXPECT_TIMEOUT_EXCEPTIONS: t.Tuple[t.Type[Exception], ...] = (
        TimeoutError,
        pexpect.exceptions.ExceptionPexpect,
    )
    INIT_START_REDIRECT_THREAD: bool = True
    PEXPECT_DEFAULT_TIMEOUT: float = 30

    def __init__(
        self,
        raw_port: T,
        name: str = '',
        log_file: str = '',
        **kwargs: t.Any,
    ) -> None:
        self._raw_port = raw_port
        self._name = name
        self._log_file = log_file
        self._kwargs = kwargs
        # __enter__ and __exit__
        self._close_redirect_thread_when_exit = True
        if 'close_redirect_thread_when_exit' in kwargs:
            self._close_redirect_thread_when_exit = kwargs['close_redirect_thread_when_exit']
        # redirect thread (pexpect spawn)
        self.expect_timeout_exceptions = self.EXPECT_TIMEOUT_EXCEPTIONS
        self.timeout = self.PEXPECT_DEFAULT_TIMEOUT
        self._pexpect_spawn: t.Optional[PortSpawn] = None
        # logger
        self._logger = self._get_logger()
        # others
        self._post_init()
        self._start()
        self._finalize_init()

    def _get_logger(self) -> logging.Logger:
        if 'logger' in self._kwargs and self._kwargs['logger']:
            return self._kwargs['logger']  # type: ignore
        logger_name = f'{self._name}' or 'port'
        return get_logger(logger_name)

    def _post_init(self) -> None:
        """Extra initialize"""
        pass  # pylint: disable=unnecessary-pass

    def _start(self) -> None:
        # TODO: logger file handler
        if self.INIT_START_REDIRECT_THREAD:
            assert self._raw_port
            assert isinstance(self._raw_port, RawPort)
            self.start_redirect_thread()

    def _finalize_init(self) -> None:
        pass

    @property
    @deprecated('use raw_port instead port')
    def port(self) -> T:
        return self._raw_port  # type: ignore

    @property
    def raw_port(self) -> T:
        return self._raw_port  # type: ignore

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value
        if self.spawn:
            self.spawn.name = value

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def _init_log_file(self) -> None:
        if self.log_file:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, 'ab+') as f:
                f.write(f'--------- Saving {self.name}:{str(self.raw_port)} logs to this file --------\n'.encode())
        else:
            self.logger.debug(f'do not save {self.name}:{str(self.raw_port)} logs to file')

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
        if self._pexpect_spawn:
            self._pexpect_spawn.log_file = new_log_file
        self._log_file = new_log_file

    @property
    def spawn(self) -> t.Optional[PortSpawn]:
        """Allow the use of pexpect spawn enhancements, if pexpect process is available"""
        return self._pexpect_spawn

    def start_redirect_thread(self) -> None:
        """Start a new thread to read data from port and save to data cache."""
        if self._pexpect_spawn:
            return
        self._init_log_file()
        self._pexpect_spawn = PortSpawn(
            self.raw_port, self.name, self.log_file, self.PEXPECT_DEFAULT_TIMEOUT, **self._kwargs
        )

    def stop_redirect_thread(self) -> bool:
        """Stop the redirect thread and pexpect process."""
        if not self._pexpect_spawn:
            return False
        self._init_log_file()
        self._pexpect_spawn.close()
        self._pexpect_spawn = None
        return True

    @contextlib.contextmanager
    def disable_redirect_thread(self) -> t.Generator[None, None, None]:
        stopped = self.stop_redirect_thread()
        yield
        if stopped:
            self.start_redirect_thread()

    @staticmethod
    def handle_expect_timeout(func: t.Callable) -> t.Callable:
        """Raise same type exception ExpectTimeout for ports from different frameworks"""

        @functools.wraps(func)
        def wrap(self, *args, **kwargs):  # type: ignore
            try:
                result = func(self, *args, **kwargs)
            except self.expect_timeout_exceptions as e:
                try:
                    data_in_buffer = self._pexpect_spawn.before  # pylint: disable=protected-access
                except AttributeError:
                    data_in_buffer = ''
                self.logger.debug(f'ExpectTimeout: {str(e)}, data_in_buffer={repr(data_in_buffer)}')
                raise ExpectTimeout(str(e), data_in_buffer=data_in_buffer) from e
            return result

        return wrap

    def write(self, data: t.AnyStr) -> None:
        if self._pexpect_spawn:
            return self._pexpect_spawn.write(data)
        raise NotImplementedError()

    def write_line(self, data: t.AnyStr, end: str = '\n') -> None:
        return self.write(to_bytes(data, end))

    @handle_expect_timeout
    def expect_exact(self, pattern: t.Union[str, bytes], timeout: float) -> None:
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

    @handle_expect_timeout
    def expect(self, pattern, timeout=PEXPECT_DEFAULT_TIMEOUT):  # type: ignore
        """This seeks through the stream until a pattern is matched.

        This expect() method is different with the one in pexpect.
        This method only accepts pattern type str/bytes or re.Pattern. Does not accept list, EOF or TIMEOUT.
        If the pattern type is str or bytes, this method is similar to expect_exact(), but returning None.
        If the pattern type is re.Pattern, this method will return a re.Match object if the pattern is matched.
        Can read all output data by pattern=re.compile('.+', re.DOTALL)

        Args:
            pattern (t.Union[str, bytes, re.Pattern]): pattern to match
            timeout (int, optional): seconds of waiting for new data if match failed. Defaults to 30s.

        Returns:
            t.Optional[re.Match]: match result if the input pattern is re.Pattern
        """
        if self._pexpect_spawn:
            if isinstance(pattern, (bytes, str)):
                self._pexpect_spawn.expect_exact(pattern, timeout=timeout)
                return None

            assert isinstance(pattern, re.Pattern)
            if isinstance(pattern.pattern, str):
                # re-compile regex pattern using bytes, with same flags
                re_flags = pattern.flags & (re.DOTALL | re.MULTILINE | re.IGNORECASE)
                pexpect_pattern = re.compile(to_bytes(pattern.pattern), re_flags)
            else:
                pexpect_pattern = pattern
            self._pexpect_spawn.expect(pexpect_pattern, timeout=timeout)
            match = self._pexpect_spawn.match
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
            # pexpect may return empty bytes if b'(.*)' is used
            try:
                match = self.expect(re.compile(b'(.+)', re.DOTALL), timeout=0)
                assert match
                buffer = match.group(0)
            except TimeoutError:
                pass
        else:
            # flush spawn buffer
            assert self._pexpect_spawn
            self._pexpect_spawn.expect_exact(pexpect.TIMEOUT, timeout=0)
            buffer = to_bytes(self._pexpect_spawn.buffer)
        assert isinstance(buffer, bytes)
        return buffer

    def close(self) -> None:
        if self._close_redirect_thread_when_exit and self._pexpect_spawn:
            self._pexpect_spawn.close()
        if self.raw_port:
            if hasattr(self.raw_port, 'close'):
                assert callable(self.raw_port.close)  # type: ignore
                self.raw_port.close()  # type: ignore

    def __enter__(self) -> 't.Self':
        return self

    def __exit__(self, exc_type, exc_value, trace) -> None:  # type: ignore
        self.close()
