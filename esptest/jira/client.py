"""Jira client creation and credential discovery."""

import base64
import os
from functools import lru_cache

import yaml

import esptest.common.compat_typing as t

DEFAULT_JIRA_URL = 'https://jira.espressif.com:8443'
DEFAULT_TIMEOUT = 1200
ACCOUNT_CONFIG_FILES = (
    lambda: os.getenv('BOT_JIRA_ACCOUNT_FILE_PATH', ''),
    lambda: 'Account.JIRA.yml',
    lambda: os.path.join(os.path.expanduser('~'), '.config', 'Account.JIRA.yml'),
)


def _read_config_file(path: str) -> t.Dict[str, str]:
    with open(path, 'rb') as config_file:
        data = config_file.read()

    config = yaml.safe_load(data)
    if not isinstance(config, dict):
        config = yaml.safe_load(base64.decodebytes(data))
    if not isinstance(config, dict):
        raise ValueError('Jira account config must contain a YAML mapping')
    return {str(key): str(value) for key, value in config.items() if value is not None}


def get_config() -> t.Dict[str, str]:
    """Return Jira credentials from CI, local environment variables, or account files."""
    token = os.getenv('CI_JIRA_TOKEN')
    username = os.getenv('CI_JIRA_USERNAME')
    password = os.getenv('CI_JIRA_PASSWORD')
    url = os.getenv('CI_JIRA_URL', DEFAULT_JIRA_URL)

    if token:
        return {'url': url, 'token': token}
    if username and password:
        return {'url': url, 'username': username, 'password': password}

    token = os.getenv('JIRA_TOKEN')
    username = os.getenv('JIRA_USERNAME')
    password = os.getenv('JIRA_PASSWORD')
    url = os.getenv('JIRA_URL', DEFAULT_JIRA_URL)

    if token:
        return {'url': url, 'token': token}
    if username and password:
        return {'url': url, 'username': username, 'password': password}

    for candidate_factory in ACCOUNT_CONFIG_FILES:
        path = candidate_factory()
        if path and os.path.isfile(path):
            config = _read_config_file(path)
            config.setdefault('url', DEFAULT_JIRA_URL)
            return config

    raise RuntimeError(
        'Jira credentials are not configured. Set CI_JIRA_TOKEN, JIRA_TOKEN, '
        'or matching CI_JIRA_USERNAME/CI_JIRA_PASSWORD or JIRA_USERNAME/JIRA_PASSWORD, '
        'or provide Account.JIRA.yml.'
    )


def get_jira_class() -> t.Any:
    """Import python-jira only when Jira functionality is used."""
    try:
        from jira import JIRA
    except ImportError as error:
        raise ImportError('Install Jira support with: pip install "esp-test-utils[jira]"') from error
    return JIRA


def create_client(
    server: t.Optional[str] = None,
    token: t.Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> t.Any:
    """Create a python-jira client, allowing CLI overrides for server and token."""
    config = {}
    if not server or not token:
        config = get_config()
    server = server or config['url']
    token = token or config.get('token')
    jira_class = get_jira_class()

    if token:
        return jira_class(
            server=server,
            token_auth=token,
            timeout=timeout,
            options={'headers': {'Connection': 'close'}},
        )
    if config.get('username') and config.get('password'):
        return jira_class(server=server, basic_auth=(config['username'], config['password']), timeout=timeout)
    raise RuntimeError('Jira account config must contain token or username and password.')


@lru_cache(maxsize=1)
def login_jira(timeout: int = DEFAULT_TIMEOUT) -> t.Any:
    """Return the cached default Jira client for the current process."""
    return create_client(timeout=timeout)
