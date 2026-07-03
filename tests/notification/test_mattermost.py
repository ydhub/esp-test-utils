# mypy: disable-error-code=no-untyped-def
import json
import urllib.error

from esptest.notification import mattermost


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return b'ok'


def test_build_text_payload_supports_markdown_and_display_overrides():
    payload = mattermost.build_text_payload(
        '## Result\n| item | status |\n| --- | --- |\n| test | pass |',
        username='ci-bot',
        icon_url='https://example.com/icon.png',
        channel='town-square',
        props_card='extra **details**',
    )

    assert payload == {
        'text': '## Result\n| item | status |\n| --- | --- |\n| test | pass |',
        'username': 'ci-bot',
        'icon_url': 'https://example.com/icon.png',
        'channel': 'town-square',
        'props': {'card': 'extra **details**'},
    }


def test_build_attachment_payload_supports_rich_fields():
    payload = mattermost.build_attachment_payload(
        attachments=[
            {
                'color': '#00cc66',
                'title': 'CI passed',
                'title_link': 'https://example.com/pipeline',
                'fields': [{'title': 'Passed', 'value': '12', 'short': True}],
            }
        ],
        text='pipeline summary',
    )

    assert payload == {
        'text': 'pipeline summary',
        'attachments': [
            {
                'color': '#00cc66',
                'title': 'CI passed',
                'title_link': 'https://example.com/pipeline',
                'fields': [{'title': 'Passed', 'value': '12', 'short': True}],
            }
        ],
    }


def test_send_mattermost_message_posts_payload(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout=0):
        sent['timeout'] = timeout
        sent['url'] = request.full_url
        sent['payload'] = json.loads(request.data.decode('utf-8'))
        sent['content_type'] = request.headers['Content-type']
        return FakeResponse()

    monkeypatch.setattr(mattermost, 'urlopen', fake_urlopen)
    result = mattermost.send_mattermost_message(
        'build failed',
        webhook_url='https://mattermost.example/hooks/abc',
        mentions='alice,bob',
        timeout=3,
        hostname='runner-01',
        prefix='CRONJOB',
    )

    assert result is True
    assert sent['timeout'] == 3
    assert sent['url'] == 'https://mattermost.example/hooks/abc'
    assert sent['content_type'] == 'application/json'
    assert sent['payload'] == {'text': '[CRONJOB] (runner-01) build failed @alice @bob'}


def test_send_mattermost_message_does_not_add_prefix_by_default(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout=0):
        sent['payload'] = json.loads(request.data.decode('utf-8'))
        return FakeResponse()

    monkeypatch.setattr(mattermost, 'urlopen', fake_urlopen)

    assert (
        mattermost.send_mattermost_message('build failed', webhook_url='https://mattermost.example/hooks/abc') is True
    )
    assert sent['payload'] == {'text': 'build failed'}


def test_send_mattermost_message_does_not_detect_hostname(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout=0):
        sent['payload'] = json.loads(request.data.decode('utf-8'))
        return FakeResponse()

    monkeypatch.setattr(mattermost, 'urlopen', fake_urlopen)

    assert (
        mattermost.send_mattermost_message(
            'build failed',
            webhook_url='https://mattermost.example/hooks/abc',
            prefix='CRONJOB',
        )
        is True
    )
    assert sent['payload'] == {'text': '[CRONJOB] build failed'}


def test_send_mattermost_message_returns_false_on_http_error(monkeypatch):
    def fake_urlopen(request, timeout=0):
        raise urllib.error.URLError('network down')

    monkeypatch.setattr(mattermost, 'urlopen', fake_urlopen)

    assert mattermost.send_mattermost_message('hello', webhook_url='https://mattermost.example/hooks/abc') is False
