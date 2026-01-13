import logging
import os
import pathlib
import sys
from typing import Any, List, Optional

import yaml

VAR_NAME_MAPPING = {
    'ap_ssid': ['RUNNER_WIFI_SSID', 'RUNNER_AP_SSID'],
    'ap_password': ['RUNNER_WIFI_PASSWORD', 'RUNNER_AP_PASSWORD'],
    'pc_nic': ['RUNNER_PC_NIC'],
    'dut1': ['ESPPORT1'],
    'dut2': ['ESPPORT2'],
    'dut3': ['ESPPORT3'],
}


def get_variable_from_env(key: str) -> Any:
    """Get test variable from shell environment

    Args:
        key (str): which variable to get
    """
    if key in VAR_NAME_MAPPING:
        for var_name in VAR_NAME_MAPPING[key]:
            var = os.getenv(var_name)
            if var is not None:
                logging.debug(f'Got env variable from shell env {var_name}: {var}')
                return var
    return None


class EnvConfig:
    """Get test environment variables from config file.

    By default the config file is named "EnvConfig.yml" and put in one of those folders:
        - env variables: TEST_ENV_CONFIG_DIR
        - Current working directory
        - project root directory
        - ci-test-runner-configs (with runner description) under project root directory
        - <HOME>/test_env_config/  # non-win32

    Support input variables from console if run tests locally other than CI.

    Example usage:

        ```python
        env_config = EnvConfig(env_tag='my_env')
        var1 = env_config.get_variable('var1')
        ```
    """

    # Set env config file directly
    ENV_CONFIG_FILE_BASE_NAME = 'EnvConfig.yml'
    TEST_ENV_CONFIG_FILE = os.getenv('TEST_ENV_CONFIG_FILE', '')
    # Find env config file from project root path
    # CI_PROJECT_DIR was set by gitlab CI
    PROJECT_ROOT_DIR = os.getenv('PROJECT_ROOT_DIR') or os.getenv('CI_PROJECT_DIR', '')
    # allow EnvConfig load shell env variables, default enabled
    DISABLE_LOAD_SHELL_ENV = os.getenv('ESPTEST_DISABLE_LOAD_SHELL_ENV', '').lower() in ('true', '1', 'yes', 'y')

    # Allow input variables from terminal during local debugging
    ALLOW_INPUT = not os.getenv('CI')

    def __init__(self, env_tag: str = 'default', config_file: Optional[str] = None) -> None:
        self.env_tag = env_tag
        if config_file:
            self.config_file = config_file
        else:
            self.config_file = self._get_config_file()
        self.config_data = {}
        if self.config_file:
            if os.path.isfile(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    raw_data = yaml.load(f.read(), Loader=yaml.FullLoader)
                assert isinstance(raw_data, dict)
                assert env_tag in raw_data
                assert isinstance(raw_data[env_tag], dict)
                self.config_data = raw_data[env_tag]
            elif not self.ALLOW_INPUT:
                raise FileNotFoundError(f'Could not optn config file: {self.config_file}')
            else:
                pass

    @classmethod
    def _reload(cls) -> None:
        """Reload to accept new environment variables. Mainly used in unit tests."""
        cls.TEST_ENV_CONFIG_FILE = os.getenv('TEST_ENV_CONFIG_FILE', '')
        cls.PROJECT_ROOT_DIR = os.getenv('PROJECT_ROOT_DIR') or os.getenv('CI_PROJECT_DIR')
        cls.ALLOW_INPUT = not os.getenv('CI')

    @classmethod
    def _search_dirs(cls) -> List[str]:
        search_dirs = []
        # Add current directory
        search_dirs.append(pathlib.Path('.'))
        # Add project root directory
        if cls.PROJECT_ROOT_DIR:
            _proj_path = pathlib.Path(cls.PROJECT_ROOT_DIR)
            search_dirs.append(_proj_path)
            search_dirs.append(_proj_path / 'ci-test-runner-configs' / os.environ.get('CI_RUNNER_DESCRIPTION', '.'))
        # Add home directory
        if sys.platform != 'win32':
            search_dirs.append(pathlib.Path.home() / 'test_env_config')
        return [str(d) for d in search_dirs if d.is_dir()]

    @classmethod
    def _get_config_file(cls) -> str:
        config_file = ''
        if cls.TEST_ENV_CONFIG_FILE:
            return cls.TEST_ENV_CONFIG_FILE
        for _dir in cls._search_dirs():
            if cls.ENV_CONFIG_FILE_BASE_NAME not in os.listdir(_dir):
                continue
            config_file = os.path.join(_dir, cls.ENV_CONFIG_FILE_BASE_NAME)
        if not config_file:
            _msg = 'Can not find env config file from:\n  ' + '  \n'.join(cls._search_dirs())
            logging.warning(_msg)
            if not cls.ALLOW_INPUT:
                raise FileNotFoundError(f'Could not find config file: {cls.ENV_CONFIG_FILE_BASE_NAME}')
            # For local test we support input variables from console
            return ''
        return config_file

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get environment variable

        Args:
            key (str): which variable to get
            default (Any, optional): default variable if the key not in config file.

        Raises:
            ValueError: raise Error if the key is not in config file and default is not given.

        Returns:
            Any: variable value
        """
        var = None
        # do not use dict.get because we can input the variable for local tests
        if key in self.config_data:
            var = self.config_data[key]
        elif default is not None:
            var = default
        else:
            if not self.DISABLE_LOAD_SHELL_ENV:
                # Try to get from shell environment variables
                var = get_variable_from_env(key)
            if var is None:
                logging.warning(f'Failed to get env variable {self.env_tag}/{key}.')
                logging.info(self.__doc__)
                if not self.ALLOW_INPUT:
                    raise ValueError(f'Env variable not found: {self.env_tag}/{key}')
                # For local test, support input the variable from console
                var = input('You can input the variable now:')
        logging.debug(f'Got env variable {self.env_tag}/{key}: {var}')
        return var
