import io
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator

import pytest

from esptest.config import EnvConfig

DEF_TEST_CONFIG = """
default:
    dut_port: /dev/ttyUSB0
wifi_ap:
    ap_ssid: wifi_ap_ssid
    ap_password: wifi_ap_password
"""


@contextmanager
def reload_envconfig(env: Dict[str, str]) -> Generator[None, None, None]:
    saved_env = os.environ.copy()
    os.environ = env  # type: ignore
    EnvConfig._reload()  # pylint: disable=protected-access
    yield
    os.environ = saved_env  # type: ignore
    EnvConfig._reload()  # pylint: disable=protected-access


def test_env_config_paths(tmp_path: Path) -> None:
    prev_env_config_file = EnvConfig.TEST_ENV_CONFIG_FILE
    original_config_file_name = EnvConfig.ENV_CONFIG_FILE_BASE_NAME
    EnvConfig.ENV_CONFIG_FILE_BASE_NAME = 'not_exist_env_config_file.yml'
    try:
        assert not os.path.exists(EnvConfig.ENV_CONFIG_FILE_BASE_NAME)
        env = {'CI': '1'}
        with reload_envconfig(env):
            assert EnvConfig.ALLOW_INPUT is False
            with pytest.raises(OSError):
                _ = EnvConfig()
    finally:
        EnvConfig.ENV_CONFIG_FILE_BASE_NAME = original_config_file_name
    # Test environment `TEST_ENV_CONFIG_FILE`
    env = {'TEST_ENV_CONFIG_FILE': str(tmp_path / 'my_config.yml')}
    with reload_envconfig(env):
        assert EnvConfig.TEST_ENV_CONFIG_FILE == str(tmp_path / 'my_config.yml')
        assert EnvConfig.ALLOW_INPUT is True
    # also test reload_envconfig
    assert EnvConfig.TEST_ENV_CONFIG_FILE == prev_env_config_file


def test_env_config_get_var(tmp_path: Path) -> None:
    config_file = tmp_path / 'my_config.yml'
    with open(config_file, 'w') as f:
        f.write(DEF_TEST_CONFIG)
    env = {'TEST_ENV_CONFIG_FILE': str(config_file), 'CI': '1'}
    with reload_envconfig(env):
        env_config = EnvConfig()
        assert env_config.get_variable('dut_port') == '/dev/ttyUSB0'
        with pytest.raises(ValueError):
            env_config.get_variable('ap_ssid')
        env_config = EnvConfig('wifi_ap')
        assert env_config.get_variable('ap_ssid') == 'wifi_ap_ssid'
        with pytest.raises(ValueError):
            env_config.get_variable('dut_port')


def test_env_config_from_shell_env(tmp_path: Path) -> None:
    # Test Get variable from console
    config_file = tmp_path / 'not_exist_config.yml'
    env = {
        'TEST_ENV_CONFIG_FILE': str(config_file),
    }
    with reload_envconfig(env):
        try:
            os.environ.pop('RUNNER_WIFI_SSID')
        except KeyError:
            pass
        try:
            os.environ.pop('RUNNER_AP_SSID')
        except KeyError:
            pass
        env_config = EnvConfig()
        env_config.ALLOW_INPUT = False
        with pytest.raises(ValueError):
            var = env_config.get_variable('ap_ssid')
        os.environ['RUNNER_AP_SSID'] = 'ssid_from_env'
        var = env_config.get_variable('ap_ssid')
        assert var == 'ssid_from_env'


def test_env_config_from_console(tmp_path, monkeypatch):  # type: ignore
    # Test Get variable from console
    config_file = tmp_path / 'not_exist_config.yml'
    env = {
        'TEST_ENV_CONFIG_FILE': str(config_file),
    }
    with reload_envconfig(env):
        env_config = EnvConfig()
        monkeypatch.setattr('sys.stdin', io.StringIO('value2'))
        var = env_config.get_variable('not_exist_key')
        assert var == 'value2'


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
