import io
import os
import subprocess
import sys
import time

import psutil

import esptest.common.compat_typing as t

from ...logger import get_logger
from .base_port import BasePort, RawPort

logger = get_logger('shell_port')


if sys.platform == 'win32':
    import wexpect as pexpect  # pexpect.spawn

    DEFAULT_SHELL = 'cmd.exe'
else:
    import pexpect

    DEFAULT_SHELL = '/bin/bash'


class ShellRaw(RawPort):
    """A subprocess Raw Port class that supports shell read, write

    is a subclass of RawPort
    """

    def __init__(self, cmd: t.Union[str, t.List[str]] = '', env: t.Optional[t.Dict[str, str]] = None) -> None:
        self.env = env or os.environ.copy()
        self.env['PYTHONUNBUFFERED'] = 'true'  # for python scripts, disable output buffering
        self.cmd = cmd or DEFAULT_SHELL
        self.proc: t.Optional[subprocess.Popen] = None
        self.read_timeout = 0.002  # default read_timeout
        self.open()

    def open(self) -> None:
        if not self.proc:
            self.proc = subprocess.Popen(  # pylint: disable=consider-using-with
                self.cmd,
                shell=bool(not isinstance(self.cmd, list)),
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            # Set stdout to non-blocking
            os.set_blocking(self.proc.stdout.fileno(), False)  # type: ignore

    def close(self) -> None:
        """Close subprocess."""
        if self.proc:
            if self.proc.pid:
                try:
                    proc = psutil.Process(self.proc.pid)
                    for child in proc.children(recursive=True):
                        child.kill()
                    proc.kill()
                    time.sleep(0.01)
                except psutil.Error:
                    pass
                # # Unix / Linux - does not work
                # try:
                #     os.killpg(self.proc.pid, signal.SIGTERM)  # send SIGTERM to all in the group
                #     os.killpg(self.proc.pid, signal.SIGKILL)  # send SIGTERM to all in the group
                # except ProcessLookupError:
                #     pass
            self.proc.terminate()
            self.proc.kill()
            self.proc.wait()
            logger.info(f'shell command [{self.cmd}] was killed')
        self.proc = None

    def write_bytes(self, data: bytes) -> None:
        """Write bytes to subprocess stdin."""
        if self.proc:
            self.proc.stdin.write(data)  # type: ignore
            self.proc.stdin.flush()  # type: ignore
            return
        raise ValueError('Subprocess not initialized.')

    def read_bytes(self, timeout: float = 0) -> bytes:
        """blocking read bytes"""
        data = self.read_bytes_nonblocking()
        if not data and timeout > 0:
            time.sleep(timeout)  # blocking read
            data = self.read_bytes_nonblocking()
        if data:
            logger.debug(f'[{self.cmd}] read_bytes timeout={timeout}, data={str(data)}')
        return data

    def read_bytes_nonblocking(self, size: int = -1) -> bytes:
        """non-blocking read bytes"""
        if self.proc:
            self.proc.stdout.flush()  # type: ignore
            return self.proc.stdout.read(size)  # type: ignore
        return b''


class ShellPort(BasePort[ShellRaw]):
    """A combined port class that supports shell read, write, expect"""

    def __init__(
        self,
        cmd: str = '/bin/bash',
        env: t.Optional[dict[str, str]] = None,
        name: str = '',
        log_file: str = '',
        **kwargs: t.Any,
    ) -> None:
        raw_port = ShellRaw(cmd=cmd, env=env)
        super().__init__(raw_port, name, log_file, **kwargs)


class InvalidRaw(RawPort):
    """A invalid Raw Port class that always raise NotImplementedError to pass type check"""

    def write_bytes(self, data: bytes) -> None:
        """Write bytes to subprocess stdin."""
        raise NotImplementedError('Invalid Raw Port.')

    def read_bytes(self, timeout: float = 0) -> bytes:
        """blocking read bytes"""
        raise NotImplementedError('Invalid Raw Port.')


class PexpectPort(BasePort[InvalidRaw]):
    """A pexpect Port class that supports shell read, write, expect

    based on pexpect.spawn but use different expect method
    """

    def __init__(
        self,
        cmd: str = '/bin/bash',
        name: str = '',
        log_file: str = '',
        **kwargs: t.Any,
    ) -> None:
        if sys.platform == 'win32':
            raise NotImplementedError('PexpectPort is not supported on Windows now.')
        self._cmd = cmd
        raw_port = InvalidRaw()
        self._pexpect_spawn: t.Optional[pexpect.spawn] = None  # change type
        self.log_file_f: t.Optional[io.BufferedWriter] = None
        if log_file:
            os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
            self.log_file_f = open(log_file, 'wb')  # pylint: disable=consider-using-with
        else:
            self.log_file_f = None
        super().__init__(raw_port, name, log_file, **kwargs)

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
        if self.log_file_f:
            if self._pexpect_spawn:
                self._pexpect_spawn.logfile = None  # type: ignore
            self.log_file_f.close()
        if new_log_file:
            os.makedirs(os.path.dirname(new_log_file) or '.', exist_ok=True)
            self.log_file_f = open(new_log_file, 'wb')  # pylint: disable=consider-using-with
        else:
            self.log_file_f = None
        if self._pexpect_spawn:
            self._pexpect_spawn.logfile = self.log_file_f  # type: ignore
        self._log_file = new_log_file

    @property
    def spawn(self) -> t.Optional[pexpect.spawn]:  # type: ignore
        """Allow the use of pexpect spawn enhancements, if pexpect process is available"""
        return self._pexpect_spawn

    def start_redirect_thread(self) -> None:
        """Start a new thread to read data from port and save to data cache."""
        if self._pexpect_spawn:
            return
        self._init_log_file()
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = 'true'  # for python scripts, disable output buffering
        self._pexpect_spawn = pexpect.spawn(self._cmd, maxread=8192, echo=False, env=env)  # type: ignore
        self._pexpect_spawn.logfile = self.log_file_f  # type: ignore
        # self._pexpect_spawn.delaybeforesend = 0.001

    def stop_redirect_thread(self) -> bool:
        """Stop the redirect thread and pexpect process."""
        if not self._pexpect_spawn:
            return False
        self._init_log_file()
        self._pexpect_spawn.close()
        self._pexpect_spawn = None  # type: ignore
        return True

    def close(self) -> None:
        """Close pexpect process."""
        super().close()
        self.stop_redirect_thread()
        if self.log_file_f:
            self.log_file_f.close()
            self.log_file_f = None
