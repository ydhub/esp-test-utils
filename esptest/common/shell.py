"""Run local commands and return stdout, stderr, and the exit code.

``run_command`` forwards extra keywords to ``subprocess.run``. Streams are
captured only when the caller asks, for example with ``capture_output=True``.
``CmdResult.output`` joins the captured streams and is always ``str``. The
streams themselves are ``str`` when ``text=True``, ``bytes`` otherwise, or
``None`` when not captured.
``run_cmd`` is a deprecated wrapper around ``run_command(cmd, check=True)``.

``timeout`` defaults to no limit. Pass ``timeout=20`` when a 20 second limit is
wanted. ``log_output`` is one of ``always``, ``on_failed``, ``on_success``, and
``never``.
"""

import os
import subprocess
import sys

from ..common import compat_typing as t
from ..logger import get_logger
from .decorators import deprecated
from .encoding import to_str
from .timestamp import timestamp_str

logger = get_logger('shell')

_LOG_OUTPUT_MODES = frozenset(('always', 'on_failed', 'on_success', 'never'))


def ensure_windows_env() -> None:
    """Ensure Windows environment variables are set for subprocess.

    Args:
        env: Environment dictionary to update
    """
    if sys.platform == 'win32':
        if 'SystemRoot' not in os.environ:
            os.environ['SystemRoot'] = 'C:\\Windows'
        if 'ComSpec' not in os.environ:
            os.environ['ComSpec'] = os.path.join(os.environ['SystemRoot'], 'System32', 'cmd.exe')


# ``CompletedProcess[T]`` is subscriptable from Python 3.9. ``T`` is the stream type.
if sys.version_info >= (3, 9):
    _CompletedProcess = subprocess.CompletedProcess[t.Optional[t.Union[str, bytes]]]
else:
    _CompletedProcess = subprocess.CompletedProcess


class CmdResult(_CompletedProcess):
    """``subprocess.CompletedProcess`` plus combined text output.

    ``args`` and ``returncode`` match ``CompletedProcess``. ``cmd`` is an alias
    of ``args``. ``stdout`` and ``stderr`` are ``str`` when ``text=True`` and
    ``bytes`` otherwise. Either is ``None`` when that stream was not captured.
    ``output`` concatenates the captured streams as ``str``. Use ``ok`` or
    ``returncode`` for status.
    """

    def __init__(  # pylint: disable=useless-parent-delegation
        self,
        args: t.Union[str, t.List[str]] = '',
        returncode: int = 0,
        stdout: t.Optional[t.Union[str, bytes]] = None,
        stderr: t.Optional[t.Union[str, bytes]] = None,
    ) -> None:
        super().__init__(args, returncode, stdout, stderr)

    @property
    def cmd(self) -> t.Union[str, t.List[str], None]:
        """Command, same object as ``args``."""
        return t.cast(t.Union[str, t.List[str], None], self.args)

    @property
    def output(self) -> str:
        """Captured stdout followed by stderr, decoded as text."""
        stdout = '' if self.stdout is None else to_str(self.stdout)
        stderr = '' if self.stderr is None else to_str(self.stderr)
        return stdout + stderr

    @property
    def ok(self) -> bool:
        """Whether the process exited 0. A timeout is not ok."""
        return self.returncode == 0


class RunCmdError(subprocess.SubprocessError):
    """Raised when ``check`` is set and the command exits non-zero."""

    def __init__(
        self,
        cmd: str,
        output: t.Union[str, bytes],
        *,
        retcode: int = 1,
        stdout: t.Optional[t.Union[str, bytes]] = None,
        stderr: t.Optional[t.Union[str, bytes]] = None,
    ) -> None:
        self.cmd = cmd
        self.output = output
        self.retcode = retcode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Command '{self.cmd}' failed with exit status {self.retcode}: {to_str(self.output)}"


def _emit_shell_log(data: str, log_file: t.Optional[str]) -> None:
    """Write a shell log line to ``log_file``, or to the module logger."""
    if log_file:
        stamped = f'\n[{timestamp_str()}]\n{data}\n'
        with open(log_file, 'a+', encoding='utf-8') as handle:
            handle.write(stamped)
        return
    logger.info(data)


def _record_result(
    succeeded: bool,
    output: str,
    detail: str,
    *,
    log_output: str,
    log_file: t.Optional[str],
) -> None:
    if succeeded:
        # A log file keeps successful output even when log_output would hide it.
        if log_output in ('always', 'on_success') or log_file:
            _emit_shell_log(f'[SUCCEED]: {output}', log_file)
        else:
            _emit_shell_log('[SUCCEED]: output ignored', log_file)
        return
    if log_output in ('always', 'on_failed'):
        _emit_shell_log(f'[FAILED]: {detail}\n{output}', log_file)
    else:
        _emit_shell_log('[FAILED]: output ignored', log_file)


def run_command(
    cmd: t.Union[str, t.List[str]],
    *,
    check: bool = False,
    timeout: t.Optional[float] = None,
    log_output: str = 'always',
    log_file: t.Optional[str] = None,
    **kwargs: t.Any,
) -> CmdResult:
    """Run a command and return stdout, stderr, and the exit code.

    A string ``cmd`` is executed through the shell. A list is executed directly.
    Extra keyword arguments are forwarded to ``subprocess.run`` (for example
    ``cwd`` and ``env``).

    Args:
        cmd: Command string or argument list.
        check: Raise ``RunCmdError`` when the exit code is non-zero.
            ``TimeoutExpired`` is re-raised when ``check`` is set and the
            command times out. Defaults to False.
        timeout: Seconds before the process is killed. ``None`` waits without
            a limit.
        log_output: ``always``, ``on_failed``, ``on_success``, or ``never``.
            ``never`` still logs that the command ran, without its output.
        log_file: Append the shell log to this file instead of the module logger.
            Successful output is written to the file even if ``log_output``
            would otherwise hide it.

    Returns:
        CmdResult: a ``CompletedProcess`` with ``args``, ``returncode``,
        ``stdout``, ``stderr``, and ``output``. Streams follow ``subprocess.run``:
        ``None`` unless captured, ``str`` when ``text=True``, otherwise
        ``bytes``. ``output`` is always ``str``. ``returncode`` is ``-1`` when
        the command times out and ``check`` is false.

    Raises:
        ValueError: ``log_output`` is not a known mode.
        RunCmdError: ``check`` is true and the process exits non-zero.
        subprocess.TimeoutExpired: ``check`` is true and ``timeout`` elapses.
    """
    if log_output not in _LOG_OUTPUT_MODES:
        modes = ', '.join(sorted(_LOG_OUTPUT_MODES))
        raise ValueError(f'log_output must be one of {modes}, got {log_output!r}')

    kwargs.pop('check', None)
    use_shell = kwargs.pop('shell') if 'shell' in kwargs else isinstance(cmd, str)
    if sys.platform == 'win32' and use_shell:
        ensure_windows_env()

    _emit_shell_log(f'[INPUT]: {cmd}', log_file)
    try:
        completed = subprocess.run(cmd, timeout=timeout, check=False, shell=use_shell, **kwargs)
    except subprocess.TimeoutExpired as exc:
        result = CmdResult(cmd, -1, stdout=exc.stdout, stderr=exc.stderr)
        _record_result(
            False,
            result.output,
            str(exc),
            log_output=log_output,
            log_file=log_file,
        )
        if check:
            raise
        return result

    result = CmdResult(cmd, int(completed.returncode), stdout=completed.stdout, stderr=completed.stderr)
    if result.returncode != 0:
        detail = f"Command '{cmd}' returned non-zero exit status {result.returncode}."
        _record_result(False, result.output, detail, log_output=log_output, log_file=log_file)
        if check:
            raise RunCmdError(
                str(cmd),
                result.output,
                retcode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result
    _record_result(True, result.output, '', log_output=log_output, log_file=log_file)
    return result


@deprecated('use run_command(check=True) instead')
def run_cmd(cmd: t.Union[str, t.List[str]], **kwargs: t.Any) -> str:
    """Run a command and return its output, raising ``RunCmdError`` on failure.

    Equivalent to ``run_command(cmd, check=True, **kwargs).output``. Pass
    ``capture_output=True`` to fill that string. It is empty when the streams
    are not captured.

    Args:
        cmd: Command string or argument list.
        kwargs: Forwarded to ``run_command``, including ``timeout``,
            ``log_output``, ``log_file``, and ``subprocess`` arguments.

    Returns:
        CmdResult: Combined stdout and stderr.

    Raises:
        RunCmdError: The command exits non-zero.
    """
    return run_command(cmd, check=True, **kwargs).output
