import abc
import contextlib
import functools
import logging
import os
import queue
import re
import sys
import threading
import time
from typing import overload

import esptest.common.compat_typing as t

from ...common import timestamp_str, to_bytes, to_str
from ...common.data_monitor import DataMonitor
from ...common.decorators import deprecated
from ...config.global_config import g
from ...interface.port import PortInterface
from ...logger import get_logger
from .data_monitor_mixin import DataMonitorMixin

if sys.platform == 'win32':
    import pexpect
    from pexpect.exceptions import ExceptionPexpect
    from pexpect.spawnbase import SpawnBase
    # from wexpect import SpawnPipe as SpawnBase
    # from wexpect import ExceptionPexpect
else:
    import pexpect
    from pexpect.exceptions import ExceptionPexpect
    from pexpect.spawnbase import SpawnBase


logger = get_logger('port')
NEVER_MATCHED_MAGIC_STRING = 'o6K,Q.(w+~yr~N9R'
PEXPECT_DEFAULT_TIMEOUT = g.PORT_EXPECT_TIMEOUT


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


class PortSpawn(SpawnBase, t.Generic[T]):
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
        timeout: float = PEXPECT_DEFAULT_TIMEOUT,
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
        self.maxread = kwargs.get('maxread', g.PORT_SPAWN_MAXREAD)
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
        # callbacks
        self._rx_log_callback: t.Optional[t.Callable[[str, bytes], None]] = kwargs.get('rx_log_callback', None)
        # monitors
        self._monitors: t.Optional[t.List[DataMonitor]] = kwargs.get('monitors', None)
        self._serial_error_reconnect_count_left = max(0, int(g.ALLOW_SERIAL_ERROR_RECONNECT_COUNT))
        self._read_thread = threading.Thread(target=self._read_incoming, name=f'Spawn_{self.name}')
        self._read_thread.daemon = True
        self._read_thread.start()

    @property
    def receive_callback(self) -> t.Optional[t.Callable[[str, bytes], None]]:
        return self._rx_log_callback

    @receive_callback.setter
    @deprecated('set receive_callback directly is deprecated, use rx_log_callback instead')
    def receive_callback(self, new_callback: t.Optional[t.Callable[[str, bytes], None]]) -> None:
        self._rx_log_callback = new_callback

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

    def _try_reconnect_after_error(self, err: Exception) -> bool:
        if self._serial_error_reconnect_count_left <= 0:
            return False
        raw_port_close = getattr(self.raw_port, 'close', None)
        raw_port_open = getattr(self.raw_port, 'open', None)
        if not callable(raw_port_close) or not callable(raw_port_open):
            self.logger.warning(f'Skip serial reconnect after serial error on {self.name}: raw port missing close/open')
            return False
        try:
            self._serial_error_reconnect_count_left -= 1
            raw_port_close()
            # Keep a short gap to avoid immediate open/read race on some serial drivers.
            time.sleep(0.1)
            raw_port_open()
            self.logger.warning(
                f'{self.name} got serial error, reopened serial, '
                f'reconnect_left={self._serial_error_reconnect_count_left}'
            )
            return True
        except Exception as reconnect_err:  # pylint: disable=broad-except
            self.logger.exception(
                f'{self.name} failed to reconnect serial after error '
                f'{type(err)}: {str(err)}, reconnect_error={type(reconnect_err)}: {str(reconnect_err)}'
            )
            return False

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
                self._log(to_bytes(f'PortReadError {type(e)}: {str(e)}'), 'read')
                self.logger.exception(f'{self.name} port read error {type(e)}: {str(e)}')
                time.sleep(0.01)  # avoid busy loop
                if self._try_reconnect_after_error(e):
                    self.logger.critical(f'{self.name} reconnected after error {type(e)}: {str(e)}')
                    new_data = f'[PortException] reconnected after error {type(e)}: {str(e)}\n'.encode()
                else:
                    self._write_port_log(to_bytes(f'[PortException] {type(e)}: {str(e)}\n'))
                    return
            if new_data:
                self._read_queue.put(new_data)
                if self._rx_log_callback:
                    # https://stackoverflow.com/questions/69732212/pylint-self-xxx-is-not-callable
                    self._rx_log_callback(self.name, new_data)  # pylint: disable=E1102
                if self._monitors:
                    for monitor in self._monitors:
                        monitor.append_data(self.name, new_data)
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
        # clear older data cache if it is larger than 2x limit
        if len(self._data_cache) >= g.DATA_CACHE_SIZE_LIMIT * 2:
            self._data_cache = self._data_cache[-g.DATA_CACHE_SIZE_LIMIT :]
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
        self._rx_log_callback = None
        self._monitors = []
        self._data_cache = b''
        self._line_cache = b''


def handle_expect_timeout(func: t.Callable) -> t.Callable:
    """Raise same type exception ExpectTimeout for ports from different frameworks"""

    @functools.wraps(func)
    def wrap(obj: 'BasePort', *args, **kwargs):  # type: ignore
        try:
            result = func(obj, *args, **kwargs)
        except obj.expect_timeout_exceptions as e:
            data_in_buffer = ''
            try:
                if obj._pexpect_spawn:  # pylint: disable=protected-access
                    data_in_buffer = obj._pexpect_spawn.before  # pylint: disable=protected-access
            except AttributeError:
                pass  # ignore
            obj.logger.debug(f'ExpectTimeout: {str(e)}, data_in_buffer={repr(data_in_buffer)}')
            raise ExpectTimeout(str(e), data_in_buffer=data_in_buffer) from e
        return result

    return wrap


class _BasePort(PortInterface):
    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:  # pylint: disable=unused-argument
        # kwargs are kept for BasePort creation and should not be forwarded
        # to the end of MRO where object.__init__ rejects extra arguments.
        super().__init__()


class BasePort(DataMonitorMixin, _BasePort, t.Generic[T]):  # pylint: disable=too-many-public-methods
    """A class to simply port methods for all devices / shell / sockets to similar usage

    - Create receive thread and pexpect spawn process for data read/expect
    - Redefine

    """

    EXPECT_TIMEOUT_EXCEPTIONS: t.Tuple[t.Type[Exception], ...] = (
        TimeoutError,
        ExceptionPexpect,
    )
    INIT_START_REDIRECT_THREAD: bool = True

    def __init__(
        self,
        raw_port: T,
        name: str = '',
        log_file: str = '',
        **kwargs: t.Any,
    ) -> None:
        super().__init__(**kwargs)
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
        self.timeout = kwargs.get('timeout', PEXPECT_DEFAULT_TIMEOUT)
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
    def rx_log_callback(self) -> t.Optional[t.Callable[[str, bytes], None]]:
        """Get Current dut log file."""
        return t.cast(t.Optional[t.Callable[[str, bytes], None]], self._kwargs.get('rx_log_callback', None))

    def set_rx_log_callback(self, new_callback: t.Optional[t.Callable[[str, bytes], None]]) -> None:
        self._kwargs['rx_log_callback'] = new_callback
        if self._pexpect_spawn:
            self._pexpect_spawn._rx_log_callback = new_callback  # pylint: disable=protected-access

    @property
    def monitors(self) -> t.List[DataMonitor]:
        return t.cast(t.List[DataMonitor], self._kwargs.setdefault('monitors', []))

    @monitors.setter
    def monitors(self, new_monitors: t.List[DataMonitor]) -> None:
        synced_monitors = list(new_monitors)
        self._kwargs['monitors'] = synced_monitors
        if self._pexpect_spawn:
            self._pexpect_spawn._monitors = synced_monitors  # pylint: disable=protected-access

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
            self.raw_port, self.name, self.log_file, PEXPECT_DEFAULT_TIMEOUT, **self._kwargs
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
    def expect(self, pattern: str, timeout: float = PEXPECT_DEFAULT_TIMEOUT) -> None: ...
    @overload
    def expect(self, pattern: bytes, timeout: float = PEXPECT_DEFAULT_TIMEOUT) -> None: ...
    @overload
    def expect(self, pattern: 're.Pattern[str]', timeout: float = PEXPECT_DEFAULT_TIMEOUT) -> 're.Match[str]': ...
    @overload
    def expect(self, pattern: 're.Pattern[bytes]', timeout: float = PEXPECT_DEFAULT_TIMEOUT) -> 're.Match[bytes]': ...

    @handle_expect_timeout
    def expect(self, pattern, timeout=PEXPECT_DEFAULT_TIMEOUT):  # type: ignore
        """This seeks through the stream until a pattern is matched.

        This expect() method is different with the one in pexpect.
        This method only accepts pattern type str/bytes or re.Pattern. Does not accept list, EOF or TIMEOUT.
        If the pattern type is str or bytes, this method is similar to expect_exact(), but returning None.
        If the pattern type is re.Pattern, this method will return a re.Match object if the pattern is matched.
        Can read all output data by pattern=re.compile('.+', re.DOTALL)

        Note:
            When matching very long data in a single read, pexpect may truncate the buffer
            due to its ``maxread`` limit. If the expected pattern can
            span a large chunk of output, increase ``maxread`` on the underlying pexpect
            spawn accordingly.

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
            while True:
                new_data = b''
                # pexpect may return empty bytes if b'(.*)' is used
                try:
                    match = self.expect(re.compile(b'(.+)', re.DOTALL), timeout=0)
                    assert match
                    new_data = match.group(0)
                except TimeoutError:
                    pass
                if not new_data:
                    break
                buffer += new_data
        else:
            # update spawn buffer
            assert self._pexpect_spawn
            self._pexpect_spawn.expect_exact(pexpect.TIMEOUT, timeout=0)
            buffer = to_bytes(self._pexpect_spawn.buffer)
            if hasattr(self._pexpect_spawn, 'data_cache'):
                buffer += to_bytes(self._pexpect_spawn.data_cache)
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
