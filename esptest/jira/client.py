"""Jira client creation and credential discovery."""

import base64
import os
from functools import lru_cache

import yaml

import esptest.common.compat_typing as t

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


def _url_from_env() -> str:
    """Return Jira URL from environment variables. CI_JIRA_URL takes precedence."""
    url = os.getenv('CI_JIRA_URL') or os.getenv('JIRA_URL')
    if url:
        return url
    raise RuntimeError('Jira URL is not configured. Set CI_JIRA_URL or JIRA_URL.')


def _apply_url(config: t.Dict[str, str], jira_url: t.Optional[str]) -> t.Dict[str, str]:
    if jira_url:
        config['url'] = jira_url
        return config
    if not config.get('url'):
        config['url'] = _url_from_env()
    return config


def get_config(jira_url: t.Optional[str] = None) -> t.Dict[str, str]:
    """Return Jira credentials from CI, local environment variables, or account files.

    Pass ``jira_url`` when the caller already has a server URL (for example
    ``create_client(server=...)`` / ``esp-jira-att --server``). That value wins
    over environment variables and account-file ``url``.
    """
    token = os.getenv('CI_JIRA_TOKEN')
    username = os.getenv('CI_JIRA_USERNAME')
    password = os.getenv('CI_JIRA_PASSWORD')

    if token:
        return _apply_url({'token': token}, jira_url)
    if username and password:
        return _apply_url({'username': username, 'password': password}, jira_url)

    token = os.getenv('JIRA_TOKEN')
    username = os.getenv('JIRA_USERNAME')
    password = os.getenv('JIRA_PASSWORD')

    if token:
        return _apply_url({'token': token}, jira_url)
    if username and password:
        return _apply_url({'username': username, 'password': password}, jira_url)

    for candidate_factory in ACCOUNT_CONFIG_FILES:
        path = candidate_factory()
        if path and os.path.isfile(path):
            return _apply_url(_read_config_file(path), jira_url)

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
    config: t.Dict[str, str] = {}
    if not server or not token:
        config = get_config(jira_url=server)
    server = server or config.get('url')
    if not server:
        raise RuntimeError('Jira URL is not configured. Set CI_JIRA_URL or JIRA_URL.')
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
