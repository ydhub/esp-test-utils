import base64
from pathlib import Path

import pytest

import esptest.common.compat_typing as t
from esptest.jira import client

_JIRA_ENV_VARS = (
    'CI_JIRA_TOKEN',
    'CI_JIRA_USERNAME',
    'CI_JIRA_PASSWORD',
    'CI_JIRA_URL',
    'JIRA_TOKEN',
    'JIRA_USERNAME',
    'JIRA_PASSWORD',
    'JIRA_URL',
    'BOT_JIRA_ACCOUNT_FILE_PATH',
)


def _clear_jira_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop host/CI Jira variables so tests do not inherit the runner environment."""
    for name in _JIRA_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_get_config_prefers_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('CI_JIRA_TOKEN', 'secret')
    monkeypatch.setenv('CI_JIRA_URL', 'https://jira.example.test')
    monkeypatch.setenv('CI_JIRA_USERNAME', 'ignored')
    monkeypatch.setenv('CI_JIRA_PASSWORD', 'ignored')

    assert client.get_config() == {'url': 'https://jira.example.test', 'token': 'secret'}


def test_get_config_uses_local_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('JIRA_TOKEN', 'local-secret')
    monkeypatch.setenv('JIRA_URL', 'https://jira.local.test')

    assert client.get_config() == {'url': 'https://jira.local.test', 'token': 'local-secret'}


def test_get_config_prefers_ci_url_over_local_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('JIRA_TOKEN', 'secret')
    monkeypatch.setenv('CI_JIRA_URL', 'https://jira.ci.test')
    monkeypatch.setenv('JIRA_URL', 'https://jira.local.test')

    assert client.get_config() == {'url': 'https://jira.ci.test', 'token': 'secret'}


def test_get_config_reads_base64_account_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    account_file = tmp_path / 'Account.JIRA.yml'
    account_file.write_bytes(base64.b64encode(b'username: user\npassword: pass\n'))
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('BOT_JIRA_ACCOUNT_FILE_PATH', str(account_file))
    monkeypatch.setenv('JIRA_URL', 'https://jira.local.test')

    assert client.get_config() == {
        'url': 'https://jira.local.test',
        'username': 'user',
        'password': 'pass',
    }


def test_get_config_requires_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('JIRA_TOKEN', 'secret')

    with pytest.raises(RuntimeError, match='Jira URL is not configured'):
        client.get_config()


def test_get_config_account_file_requires_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    account_file = tmp_path / 'Account.JIRA.yml'
    account_file.write_text('username: user\npassword: pass\n', encoding='utf-8')
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('BOT_JIRA_ACCOUNT_FILE_PATH', str(account_file))

    with pytest.raises(RuntimeError, match='Jira URL is not configured'):
        client.get_config()


def test_get_config_raises_when_credentials_are_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('BOT_JIRA_ACCOUNT_FILE_PATH', str(tmp_path / 'missing.yml'))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(client.os.path, 'expanduser', lambda _: str(tmp_path / 'home'))

    with pytest.raises(RuntimeError, match='Jira credentials are not configured'):
        client.get_config()


def test_create_client_uses_token_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: t.List[t.Dict[str, object]] = []

    class FakeJira:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(client, 'get_config', lambda **_: {'url': 'https://jira.example.test', 'token': 'stored'})
    monkeypatch.setattr(client, 'get_jira_class', lambda: FakeJira)

    client.create_client(token='override', timeout=42)

    assert calls == [
        {
            'server': 'https://jira.example.test',
            'token_auth': 'override',
            'timeout': 42,
            'options': {'headers': {'Connection': 'close'}},
        }
    ]


def test_get_config_uses_passed_jira_url_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('CI_JIRA_TOKEN', 'secret')

    assert client.get_config(jira_url='https://jira.override.test') == {
        'url': 'https://jira.override.test',
        'token': 'secret',
    }


def test_get_config_passed_jira_url_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('CI_JIRA_TOKEN', 'secret')
    monkeypatch.setenv('CI_JIRA_URL', 'https://jira.ci.test')

    assert client.get_config(jira_url='https://jira.override.test') == {
        'url': 'https://jira.override.test',
        'token': 'secret',
    }


def test_create_client_uses_explicit_server_and_env_token_without_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: t.List[t.Dict[str, object]] = []

    class FakeJira:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('CI_JIRA_TOKEN', 'secret')
    monkeypatch.setattr(client, 'get_jira_class', lambda: FakeJira)

    client.create_client(server='https://jira.override.test')

    assert calls == [
        {
            'server': 'https://jira.override.test',
            'token_auth': 'secret',
            'timeout': client.DEFAULT_TIMEOUT,
            'options': {'headers': {'Connection': 'close'}},
        }
    ]


def test_create_client_uses_explicit_server_and_env_basic_auth_without_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: t.List[t.Dict[str, object]] = []

    class FakeJira:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    _clear_jira_env(monkeypatch)
    monkeypatch.setenv('JIRA_USERNAME', 'user')
    monkeypatch.setenv('JIRA_PASSWORD', 'pass')
    monkeypatch.setattr(client, 'get_jira_class', lambda: FakeJira)

    client.create_client(server='https://jira.override.test')

    assert calls == [
        {
            'server': 'https://jira.override.test',
            'basic_auth': ('user', 'pass'),
            'timeout': client.DEFAULT_TIMEOUT,
        }
    ]


def test_create_client_uses_explicit_server_and_token_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: t.List[t.Dict[str, object]] = []

    class FakeJira:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(client, 'get_config', lambda **_: pytest.fail('get_config should not be called'))
    monkeypatch.setattr(client, 'get_jira_class', lambda: FakeJira)

    client.create_client(server='https://jira.example.test', token='override', timeout=42)

    assert calls == [
        {
            'server': 'https://jira.example.test',
            'token_auth': 'override',
            'timeout': 42,
            'options': {'headers': {'Connection': 'close'}},
        }
    ]


def test_create_client_uses_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: t.List[t.Dict[str, object]] = []

    class FakeJira:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        client,
        'get_config',
        lambda **_: {'url': 'https://jira.example.test', 'username': 'user', 'password': 'pass'},
    )
    monkeypatch.setattr(client, 'get_jira_class', lambda: FakeJira)

    client.create_client()

    assert calls == [
        {
            'server': 'https://jira.example.test',
            'basic_auth': ('user', 'pass'),
            'timeout': client.DEFAULT_TIMEOUT,
        }
    ]
