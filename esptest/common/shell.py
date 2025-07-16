import subprocess

from ..common import compat_typing as t
from ..logger import get_logger

logger = get_logger('shell')


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
        output = subprocess.check_output(cmd, shell=_shell, text=True, stderr=subprocess.STDOUT, **kwargs)
        logger.debug(f'output of "{str(cmd)}": {output}')
    except subprocess.CalledProcessError as e:
        logger.debug(str(e))
        raise RunCmdError(str(e.cmd), e.output) from e
    assert isinstance(output, str)
    return output
