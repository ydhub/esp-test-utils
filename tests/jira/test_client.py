import base64

import pytest

from esptest.jira import client


def test_get_config_prefers_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CI_JIRA_TOKEN', 'secret')
    monkeypatch.setenv('CI_JIRA_URL', 'https://jira.example.test')
    monkeypatch.setenv('CI_JIRA_USERNAME', 'ignored')
    monkeypatch.setenv('CI_JIRA_PASSWORD', 'ignored')

    assert client.get_config() == {'url': 'https://jira.example.test', 'token': 'secret'}


def test_get_config_uses_local_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('CI_JIRA_TOKEN', raising=False)
    monkeypatch.delenv('CI_JIRA_USERNAME', raising=False)
    monkeypatch.delenv('CI_JIRA_PASSWORD', raising=False)
    monkeypatch.setenv('JIRA_TOKEN', 'local-secret')
    monkeypatch.setenv('JIRA_URL', 'https://jira.local.test')

    assert client.get_config() == {'url': 'https://jira.local.test', 'token': 'local-secret'}


def test_get_config_reads_base64_account_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    account_file = tmp_path / 'Account.JIRA.yml'
    account_file.write_bytes(base64.b64encode(b'username: user\npassword: pass\n'))
    monkeypatch.delenv('CI_JIRA_TOKEN', raising=False)
    monkeypatch.delenv('CI_JIRA_USERNAME', raising=False)
    monkeypatch.delenv('CI_JIRA_PASSWORD', raising=False)
    monkeypatch.delenv('JIRA_TOKEN', raising=False)
    monkeypatch.delenv('JIRA_USERNAME', raising=False)
    monkeypatch.delenv('JIRA_PASSWORD', raising=False)
    monkeypatch.setenv('BOT_JIRA_ACCOUNT_FILE_PATH', str(account_file))

    assert client.get_config() == {
        'url': client.DEFAULT_JIRA_URL,
        'username': 'user',
        'password': 'pass',
    }


def test_get_config_raises_when_credentials_are_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv('CI_JIRA_TOKEN', raising=False)
    monkeypatch.delenv('CI_JIRA_USERNAME', raising=False)
    monkeypatch.delenv('CI_JIRA_PASSWORD', raising=False)
    monkeypatch.delenv('JIRA_TOKEN', raising=False)
    monkeypatch.delenv('JIRA_USERNAME', raising=False)
    monkeypatch.delenv('JIRA_PASSWORD', raising=False)
    monkeypatch.setenv('BOT_JIRA_ACCOUNT_FILE_PATH', str(tmp_path / 'missing.yml'))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(client.os.path, 'expanduser', lambda _: str(tmp_path / 'home'))

    with pytest.raises(RuntimeError, match='Jira credentials are not configured'):
        client.get_config()


def test_create_client_uses_token_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeJira:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(client, 'get_config', lambda: {'url': 'https://jira.example.test', 'token': 'stored'})
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


def test_create_client_uses_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeJira:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        client,
        'get_config',
        lambda: {'url': 'https://jira.example.test', 'username': 'user', 'password': 'pass'},
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
