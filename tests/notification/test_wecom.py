# mypy: disable-error-code=no-untyped-def
import json
import urllib.error

from esptest.notification import wecom


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.body


def test_build_text_payload_supports_mentions():
    payload = wecom.build_text_payload(
        'hello',
        mentioned_list=['alice', '@all'],
        mentioned_mobile_list=['13800001111'],
    )

    assert payload == {
        'msgtype': 'text',
        'text': {
            'content': 'hello',
            'mentioned_list': ['alice', '@all'],
            'mentioned_mobile_list': ['13800001111'],
        },
    }


def test_build_markdown_payload_supports_markdown_v2():
    payload = wecom.build_markdown_payload('| item | status |\n| --- | --- |\n| test | pass |', msgtype='markdown_v2')

    assert payload == {
        'msgtype': 'markdown_v2',
        'markdown_v2': {'content': '| item | status |\n| --- | --- |\n| test | pass |'},
    }


def test_build_news_payload_supports_articles():
    payload = wecom.build_news_payload(
        [
            {
                'title': 'CI report',
                'description': 'latest pipeline result',
                'url': 'https://example.com/pipeline',
                'picurl': 'https://example.com/image.png',
            }
        ]
    )

    assert payload == {
        'msgtype': 'news',
        'news': {
            'articles': [
                {
                    'title': 'CI report',
                    'description': 'latest pipeline result',
                    'url': 'https://example.com/pipeline',
                    'picurl': 'https://example.com/image.png',
                }
            ]
        },
    }


def test_build_template_card_payload_supports_text_notice():
    card = {
        'card_type': 'text_notice',
        'main_title': {'title': 'Deployment finished', 'desc': 'staging'},
        'card_action': {'type': 1, 'url': 'https://example.com/deploy'},
    }

    assert wecom.build_template_card_payload(card) == {'msgtype': 'template_card', 'template_card': card}


def test_send_wecom_message_posts_payload_and_checks_errcode(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout=0):
        sent['timeout'] = timeout
        sent['url'] = request.full_url
        sent['payload'] = json.loads(request.data.decode('utf-8'))
        sent['content_type'] = request.headers['Content-type']
        return FakeResponse(b'{"errcode": 0, "errmsg": "ok"}')

    monkeypatch.setattr(wecom, 'urlopen', fake_urlopen)

    result = wecom.send_wecom_message(
        'hello **world**',
        webhook_url='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc',
        timeout=5,
    )

    assert result is True
    assert sent['timeout'] == 5
    assert sent['url'] == 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc'
    assert sent['content_type'] == 'application/json; charset=utf-8'
    assert sent['payload'] == {'msgtype': 'markdown', 'markdown': {'content': 'hello **world**'}}


def test_send_wecom_message_appends_mentions_to_markdown(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout=0):
        sent['payload'] = json.loads(request.data.decode('utf-8'))
        return FakeResponse(b'{"errcode": 0, "errmsg": "ok"}')

    monkeypatch.setattr(wecom, 'urlopen', fake_urlopen)

    result = wecom.send_wecom_message(
        'hello **world**',
        webhook_url='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc',
        mentions=['alice', 'bob'],
    )

    assert result is True
    assert sent['payload'] == {'msgtype': 'markdown', 'markdown': {'content': 'hello **world**\n\n<@alice> <@bob>'}}


def test_send_wecom_message_uses_text_mentions_for_text_message(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout=0):
        sent['payload'] = json.loads(request.data.decode('utf-8'))
        return FakeResponse(b'{"errcode": 0, "errmsg": "ok"}')

    monkeypatch.setattr(wecom, 'urlopen', fake_urlopen)

    result = wecom.send_wecom_message(
        'hello world',
        webhook_url='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc',
        msgtype='text',
        mentions='alice,bob',
    )

    assert result is True
    assert sent['payload'] == {
        'msgtype': 'text',
        'text': {'content': 'hello world', 'mentioned_list': ['alice', 'bob']},
    }


def test_send_wecom_message_returns_false_on_wecom_error(monkeypatch):
    def fake_urlopen(request, timeout=0):
        return FakeResponse(b'{"errcode": 40001, "errmsg": "invalid credential"}')

    monkeypatch.setattr(wecom, 'urlopen', fake_urlopen)

    assert (
        wecom.send_wecom_message('hello', webhook_url='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc')
        is False
    )


def test_send_wecom_message_returns_false_on_network_error(monkeypatch):
    def fake_urlopen(request, timeout=0):
        raise urllib.error.URLError('network down')

    monkeypatch.setattr(wecom, 'urlopen', fake_urlopen)

    assert (
        wecom.send_wecom_message('hello', webhook_url='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc')
        is False
    )
