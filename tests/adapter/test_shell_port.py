import random
import re
import subprocess
import time
from pathlib import Path

import pytest

from esptest.adapter.port.shell_port import PexpectPort, ShellPort, ShellRaw


def test_shell_raw_open_close() -> None:
    ran_int = random.randint(12345678, 87654321)
    raw_port = ShellRaw(cmd=f'sleep {ran_int}')
    assert raw_port.proc is not None
    output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
    assert f'sleep {ran_int}' in output
    raw_port.close()
    output = subprocess.check_output(f'ps -ef | grep {ran_int}', shell=True).decode('utf-8')
    assert f'sleep {ran_int}' not in output


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
    with ShellPort(cmd='/bin/bash') as port:
        port.write_line('echo hello')
        time.sleep(0.1)  # wait for the receive thread
        assert 'hello' in port.read_all_data()
        port.write_line('sleep 0.1 && echo world')
        assert 'world' not in port.read_all_data()
        match = port.expect(re.compile('world'))
        assert match.group(0) == 'world'


def test_shell_port_logfile(tmp_path: Path) -> None:
    log_file = tmp_path / 'shell_port1.log'
    with ShellPort(cmd='/bin/bash', log_file=str(log_file)) as port:
        port.write_line('echo hello')
        time.sleep(0.1)  # wait for the receive thread
        with open(str(log_file), 'r') as f:
            assert 'hello' in f.read()
        port.log_file = str(tmp_path / 'shell_port2.log')
        port.write_line('echo world')
        time.sleep(0.1)  # wait for the receive thread
        with open(str(tmp_path / 'shell_port2.log'), 'r') as f:
            assert 'world' in f.read()


def test_pexpect_spawn_port_read_write() -> None:
    with PexpectPort(cmd='/bin/bash') as port:
        port.write_line('echo hello')
        time.sleep(0.5)  # wait for the receive thread
        assert 'hello' in port.read_all_data()
        port.write_line('sleep 0.1 && echo world')
        assert 'world' not in port.read_all_data()
        match = port.expect(re.compile('world'))
        assert match.group(0) == 'world'


def test_pexpect_spawn_port_logfile(tmp_path: Path) -> None:
    log_file = tmp_path / 'shell_port1.log'
    with PexpectPort(cmd='/bin/bash', log_file=str(log_file)) as port:
        port.write_line('echo hello')
        time.sleep(0.5)  # wait for the receive thread
        with open(str(log_file), 'r') as f:
            assert 'hello' in f.read()
        port.log_file = str(tmp_path / 'shell_port2.log')
        port.write_line('echo world')
        time.sleep(0.1)  # wait for the receive thread
        with open(str(tmp_path / 'shell_port2.log'), 'r') as f:
            assert 'world' in f.read()


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
