import logging
import subprocess
import sys
import time
from pathlib import Path

import pytest

from esptest.common.shell import CmdResult, RunCmdError, run_command


def test_cmd_result_matches_completed_process() -> None:
    result = CmdResult(['echo', 'hi'], 0, stdout='hi\n', stderr='')
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.args == ['echo', 'hi']
    assert result.returncode == 0
    assert result.cmd == ['echo', 'hi']
    assert result.ok is True
    result.check_returncode()
    failed = CmdResult('false', 1, stderr='no')
    with pytest.raises(subprocess.CalledProcessError):
        failed.check_returncode()


def test_cmd_result_output_is_stdout_plus_stderr() -> None:
    result = CmdResult('echo', 0, stdout='out\n', stderr='err\n')
    assert result.output == 'out\nerr\n'
    assert result.stdout == 'out\n'
    assert result.stderr == 'err\n'
    assert result.returncode == 0
    assert result.ok is True
    assert result.cmd == 'echo'
    result.stdout = 'OUT'
    assert result.output == 'OUTerr\n'


def test_cmd_result_streams_may_be_none() -> None:
    result = CmdResult(stdout=None, stderr='err')
    assert result.stdout is None
    assert result.output == 'err'
    empty = CmdResult()
    assert empty.stdout is None
    assert empty.stderr is None
    assert empty.output == ''


def test_run_command_does_not_capture_unless_asked() -> None:
    result = run_command([sys.executable, '-c', 'import sys; sys.exit(0)'])
    assert result.stdout is None
    assert result.stderr is None
    assert result.output == ''
    assert result.ok is True


def test_run_command_keeps_uncaptured_stream_as_none() -> None:
    result = run_command(
        [sys.executable, '-c', 'print("out")'],
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )
    assert result.stdout == 'out\n'
    assert result.stderr is None
    assert result.output == 'out\n'


def test_cmd_result_output_is_always_str() -> None:
    result = CmdResult(stdout=b'out\n', stderr=b'err\n')
    assert result.output == 'out\nerr\n'
    mixed = CmdResult(stdout='out', stderr=b'err')
    assert mixed.output == 'outerr'
    binary = CmdResult(stdout=b'\xff', stderr=b'')
    assert binary.output == '\ufffd'


def test_run_command_success_separates_streams() -> None:
    code = 'import sys; sys.stdout.write("out\\n"); sys.stderr.write("err\\n")'
    result = run_command([sys.executable, '-c', code], capture_output=True, text=True)
    assert isinstance(result, CmdResult)
    assert result.returncode == 0
    assert result.ok is True
    assert result.stdout == 'out\n'
    assert result.stderr == 'err\n'
    assert result.output == 'out\nerr\n'


def test_run_command_text_false_keeps_bytes() -> None:
    code = 'import sys; sys.stdout.buffer.write(b"out\\n"); sys.stderr.buffer.write(b"err\\n")'
    result = run_command([sys.executable, '-c', code], capture_output=True, text=False)
    assert result.stdout == b'out\n'
    assert result.stderr == b'err\n'
    assert result.output == 'out\nerr\n'


def test_run_command_empty_output_is_success() -> None:
    result = run_command([sys.executable, '-c', 'import sys; sys.exit(0)'], capture_output=True, text=True)
    assert result.stdout == ''
    assert result.stderr == ''
    assert result.output == ''
    assert result.ok is True


def test_run_command_failure_returns_retcode_without_raising() -> None:
    result = run_command([sys.executable, '-c', 'import sys; sys.exit(3)'])
    assert result.returncode == 3
    assert result.ok is False


def test_run_command_check_raises_run_cmd_error() -> None:
    with pytest.raises(RunCmdError) as exc_info:
        run_command([sys.executable, '-c', 'import sys; sys.exit(3)'], check=True, capture_output=True, text=True)
    assert exc_info.value.retcode == 3
    assert exc_info.value.stdout == ''
    assert '3' in str(exc_info.value)


def test_run_command_check_returns_output() -> None:
    result = run_command('echo hello', check=True, capture_output=True, text=True)
    assert isinstance(result, CmdResult)
    assert result.output == 'hello\n'
    assert result.returncode == 0
    assert result.stdout == 'hello\n'
    with pytest.raises(RunCmdError):
        run_command([sys.executable, '-c', 'import sys; sys.exit(4)'], check=True)


def test_run_command_passes_subprocess_kwargs(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, '-c', 'import os; print(os.getcwd())'],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert str(tmp_path) in result.output


def test_run_command_timeout_check_raises() -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, '-c', 'import time; time.sleep(30)'], check=True, timeout=0.2)
    assert time.monotonic() - started < 5


def test_run_command_timeout_without_check_returns_result() -> None:
    started = time.monotonic()
    result = run_command([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.2)
    assert time.monotonic() - started < 5
    assert result.returncode == -1
    assert result.ok is False


def test_run_command_log_output_always(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger='esptest.shell'):
        result = run_command('echo hello-log', log_output='always', capture_output=True, text=True)
    assert result.stdout == 'hello-log\n'
    assert '[INPUT]' in caplog.text
    assert 'echo hello-log' in caplog.text
    assert '[SUCCEED]: hello-log' in caplog.text


def test_run_command_log_output_never_hides_body(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger='esptest.shell'):
        run_command('echo hello-hidden', log_output='never', capture_output=True, text=True)
    assert '[SUCCEED]: output ignored' in caplog.text
    assert 'hello-hidden' not in caplog.text.split('[SUCCEED]', 1)[-1]


def test_run_command_log_output_on_failed_hides_success_body(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger='esptest.shell'):
        run_command('echo hello-success', log_output='on_failed', capture_output=True, text=True)
    assert '[SUCCEED]: output ignored' in caplog.text


def test_run_command_log_output_on_success_hides_failure_body(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    script = tmp_path / 'fail.py'
    script.write_text('import sys\nsys.stderr.write("secret-err\\n")\nsys.exit(9)\n', encoding='utf-8')
    with caplog.at_level(logging.INFO, logger='esptest.shell'):
        result = run_command([sys.executable, str(script)], log_output='on_success', capture_output=True, text=True)
    assert result.returncode == 9
    assert result.stderr == 'secret-err\n'
    assert '[FAILED]: output ignored' in caplog.text
    assert 'secret-err' not in caplog.text


def test_run_command_failure_logs_at_info(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger='esptest.shell'):
        result = run_command([sys.executable, '-c', 'import sys; sys.exit(7)'], log_output='never')
    assert result.returncode == 7
    assert '[FAILED]: output ignored' in caplog.text
    assert any(record.levelno == logging.INFO for record in caplog.records)
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)


def test_run_command_log_file_replaces_logger(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    log_file = tmp_path / 'shell.log'
    with caplog.at_level(logging.INFO, logger='esptest.shell'):
        result = run_command('echo hello-file', log_file=str(log_file), capture_output=True, text=True)
    text = log_file.read_text(encoding='utf-8')
    assert result.output == 'hello-file\n'
    assert '[INPUT]' in text
    assert 'echo hello-file' in text
    assert '[SUCCEED]' in text
    assert 'hello-file' in text
    assert 'hello-file' not in caplog.text


def test_run_command_rejects_unknown_log_output() -> None:
    with pytest.raises(ValueError):
        run_command('echo hello', log_output='sometimes')
