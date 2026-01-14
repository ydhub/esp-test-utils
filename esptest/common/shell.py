import os
import subprocess
import sys

from ..common import compat_typing as t
from ..logger import get_logger

logger = get_logger('shell')


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


class RunCmdError(subprocess.SubprocessError):
    def __init__(self, cmd: str, output: str) -> None:
        self.cmd = cmd
        self.output = output

    def __str__(self) -> str:
        return f"Command '{self.cmd}' failed: {self.output}"


def run_cmd(cmd: t.Union[str, t.List[str]], **kwargs: t.Any) -> str:
    """Run shell command and get output with redirect stderr to stdout

    Args:
        cmd (Union[str, List[str]]): command string or args
        kwargs (Any): extra args pass to subprocess

    Raises:
        RunCmdError: raise error with output

    Returns:
        str: command output
    """
    output = ''
    try:
        _shell = bool(isinstance(cmd, str))
        # Ensure Windows environment variables are set when using shell=True
        if sys.platform == 'win32' and _shell:
            ensure_windows_env()
        output = subprocess.check_output(cmd, shell=_shell, text=True, stderr=subprocess.STDOUT, **kwargs)
        logger.debug(f'output of "{str(cmd)}": {output}')
    except subprocess.CalledProcessError as e:
        logger.debug(str(e))
        raise RunCmdError(str(e.cmd), e.output) from e
    assert isinstance(output, str)
    return output
