import json
import os
from typing import Any, Dict, Mapping, Optional, Sequence, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from ..logger import get_logger
except ImportError:
    from esptest.logger import get_logger

logger = get_logger(__name__)


MATTERMOST_WEBHOOK_ENV = 'MATTERMOST_WEBHOOK_URL'


def _clean_optional(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _get_webhook_url(webhook_url: Optional[str]) -> str:
    if isinstance(webhook_url, str) and webhook_url.strip():
        return webhook_url.strip()
    return os.getenv(MATTERMOST_WEBHOOK_ENV, '').strip()


def _build_mentions(mentions: Optional[str]) -> str:
    if not mentions:
        return ''
    mention_list = [f'@{mention.strip()}' for mention in mentions.split(',') if mention.strip()]
    return ' '.join(mention_list)


def _is_valid_url(url: str) -> bool:
    parsed_url = urlparse(url)
    return bool(parsed_url.scheme and parsed_url.netloc)


def build_text_payload(
    text: str,
    username: Optional[str] = None,
    icon_url: Optional[str] = None,
    channel: Optional[str] = None,
    props_card: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Mattermost incoming webhook payload with Markdown text."""
    payload = _clean_optional(
        {
            'text': text,
            'username': username,
            'icon_url': icon_url,
            'channel': channel,
        }
    )
    if props_card is not None:
        payload['props'] = {'card': props_card}
    return payload


def build_attachment_payload(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    attachments: Sequence[Mapping[str, Any]],
    text: Optional[str] = None,
    username: Optional[str] = None,
    icon_url: Optional[str] = None,
    channel: Optional[str] = None,
    props_card: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Mattermost payload with rich Slack-compatible attachments."""
    payload = build_text_payload(
        text or '',
        username=username,
        icon_url=icon_url,
        channel=channel,
        props_card=props_card,
    )
    if text is None:
        payload.pop('text', None)
    payload['attachments'] = [dict(attachment) for attachment in attachments]
    return payload


def _build_message_payload(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    message: str,
    mentions: Optional[str] = None,
    username: Optional[str] = None,
    icon_url: Optional[str] = None,
    channel: Optional[str] = None,
    props_card: Optional[str] = None,
    prefix: Optional[str] = None,
    hostname: Optional[str] = None,
) -> Dict[str, Any]:
    text = message
    if prefix:
        text = f'[{prefix}] ({hostname}) {message}' if hostname else f'[{prefix}] {message}'
    mention_text = _build_mentions(mentions)
    if mention_text:
        text = f'{text} {mention_text}'
    return build_text_payload(text, username=username, icon_url=icon_url, channel=channel, props_card=props_card)


def send_mattermost_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    message: Union[str, Mapping[str, Any]],
    webhook_url: Optional[str] = None,
    mentions: Optional[str] = None,
    timeout: float = 10,
    username: Optional[str] = None,
    icon_url: Optional[str] = None,
    channel: Optional[str] = None,
    props_card: Optional[str] = None,
    prefix: Optional[str] = None,
    hostname: Optional[str] = None,
) -> bool:
    """Send a Mattermost incoming webhook message.

    String messages can add an optional prefix, hostname, and mentions. Mapping
    messages are sent as provided.
    """
    webhook_url = _get_webhook_url(webhook_url)
    if not webhook_url or not _is_valid_url(webhook_url):
        logger.warning('Mattermost notification failed: invalid webhook URL configured.')
        return False

    if isinstance(message, str):
        if not message.strip():
            return False
        payload = _build_message_payload(
            message,
            mentions=mentions,
            username=username,
            icon_url=icon_url,
            channel=channel,
            props_card=props_card,
            prefix=prefix,
            hostname=hostname,
        )
    else:
        payload = dict(message)

    request = Request(
        webhook_url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = getattr(response, 'status', None)
            if status_code is None:
                status_code = response.getcode()
            if not 200 <= status_code < 300:
                logger.warning('Mattermost notification failed: HTTP status %s', status_code)
                return False
            return True
    except HTTPError as e:
        logger.warning('Mattermost notification failed: HTTP status %s', e.code)
    except (URLError, OSError) as e:
        logger.warning('Mattermost notification failed: %s', type(e).__name__)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning('Mattermost notification failed: unexpected %s', type(e).__name__)
    return False
