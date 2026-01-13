import random
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from esptest.adapter.port.shell_port import PexpectPort, ShellPort, ShellRaw


@pytest.mark.skipif(sys.platform == 'win32', reason='windows does not support ps')
def test_shell_raw_open_close() -> None:
    ran_int = random.randint(12345678, 87654321)
    raw_port = ShellRaw(cmd=f'sleep {ran_int}')
    assert raw_port.proc is not None
    output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
    assert f'sleep {ran_int}' in output
    raw_port.close()
    output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
    assert f'sleep {ran_int}' not in output


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows test')
def test_shell_raw_open_close_win32() -> None:
    ran_int = random.randint(12345678, 87654321)
    raw_port = ShellRaw(cmd=['ping', '-n', str(ran_int), '127.0.0.1'])
    assert raw_port.proc is not None
    pid = raw_port.proc.pid
    output = subprocess.check_output(f'tasklist /FI "PID eq {pid}"', shell=True).decode('utf-8', errors='ignore')
    assert 'cmd.exe' in output
    raw_port.close()
    output = subprocess.check_output(f'tasklist /FI "PID eq {pid}"', shell=True).decode('utf-8', errors='ignore')
    assert 'cmd.exe' not in output


@pytest.mark.skipif(sys.platform == 'win32', reason='windows does not support ps')
def test_shell_port_open_close() -> None:
    ran_int = random.randint(12345678, 87654321)
    # close by close method
    port = ShellPort(cmd=f'sleep {ran_int}')
    assert isinstance(port.raw_port, ShellRaw)
    output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
    assert f'sleep {ran_int}' in output
    port.close()
    output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
    assert f'sleep {ran_int}' not in output
    # close by with statement
    with ShellPort(cmd=f'sleep {ran_int}') as port:
        assert isinstance(port.raw_port, ShellRaw)
        output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
        assert f'sleep {ran_int}' in output
    output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
    assert f'sleep {ran_int}' not in output


def test_shell_port_read_write() -> None:
    if sys.platform != 'win32':
        shell_cmd = '/bin/bash'
        echo_cmd1 = 'echo hello'
        echo_cmd2 = 'sleep 0.1; echo world'
    else:
        # Use cmd.exe for Windows as it's more reliable for interactive commands
        shell_cmd = 'cmd.exe'
        echo_cmd1 = 'echo hello'
        echo_cmd2 = 'timeout /t 1 /nobreak >nul & echo world'
    with ShellPort(cmd=shell_cmd, text=True) as port:
        port.write_line(echo_cmd1, end='\r\n')
        time.sleep(0.2)  # wait for the receive thread
        assert 'hello' in port.read_all_data()
        port.write_line(echo_cmd2, end='\r\n')
        assert 'world' not in port.read_all_data()
        match = port.expect(re.compile('world'))
        assert match.group(0) == 'world'


def test_shell_port_logfile(tmp_path: Path) -> None:
    log_file = tmp_path / 'shell_port1.log'
    shell_cmd = '/bin/bash' if sys.platform != 'win32' else 'cmd.exe'
    with ShellPort(cmd=shell_cmd, log_file=str(log_file)) as port:
        port.write_line('echo hello')
        time.sleep(0.1)  # wait for the receive thread
        with open(str(log_file), 'r', encoding='utf-8', errors='ignore') as f:
            assert 'hello' in f.read()
        port.log_file = str(tmp_path / 'shell_port2.log')
        port.write_line('echo world')
        time.sleep(0.1)  # wait for the receive thread
        with open(str(tmp_path / 'shell_port2.log'), 'r', encoding='utf-8', errors='ignore') as f:
            assert 'world' in f.read()


@pytest.mark.skipif(sys.platform == 'win32', reason='wexpect has issues with PowerShell/cmd.exe on Windows')
def test_pexpect_spawn_port_read_write() -> None:
    shell_cmd = '/bin/bash'
    with PexpectPort(cmd=shell_cmd) as port:
        port.write_line('echo hello')
        time.sleep(0.5)  # wait for the receive thread
        assert 'hello' in port.read_all_data()
        port.write_line('sleep 0.1 && echo world')
        assert 'world' not in port.read_all_data()
        match = port.expect(re.compile('world'))
        assert match.group(0) == 'world'


@pytest.mark.skipif(sys.platform == 'win32', reason='wexpect has issues with PowerShell/cmd.exe on Windows')
def test_pexpect_spawn_port_logfile(tmp_path: Path) -> None:
    log_file = tmp_path / 'shell_port1.log'
    shell_cmd = '/bin/bash'
    with PexpectPort(cmd=shell_cmd, log_file=str(log_file)) as port:
        port.write_line('echo hello')
        time.sleep(0.5)  # wait for the receive thread
        with open(str(log_file), 'r', encoding='utf-8', errors='ignore') as f:
            assert 'hello' in f.read()
        port.log_file = str(tmp_path / 'shell_port2.log')
        port.write_line('echo world')
        time.sleep(0.1)  # wait for the receive thread
        with open(str(tmp_path / 'shell_port2.log'), 'r', encoding='utf-8', errors='ignore') as f:
            assert 'world' in f.read()


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
