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

WECOM_WEBHOOK_ENV = 'WECOM_WEBHOOK_URL'
WECOM_MARKDOWN_MAX_BYTES = 4096
TRUNCATION_SUFFIX = '\n\n> 内容过长，已截断'


def _get_webhook_url(webhook_url: Optional[str]) -> str:
    if isinstance(webhook_url, str) and webhook_url.strip():
        return webhook_url.strip()
    return os.getenv(WECOM_WEBHOOK_ENV, '').strip()


def _is_valid_url(url: str) -> bool:
    parsed_url = urlparse(url)
    return bool(parsed_url.scheme and parsed_url.netloc)


def _truncate_utf8(content: str, max_bytes: int = WECOM_MARKDOWN_MAX_BYTES) -> str:
    content_bytes = content.encode('utf-8')
    if len(content_bytes) <= max_bytes:
        return content

    suffix_bytes = TRUNCATION_SUFFIX.encode('utf-8')
    max_content_bytes_len = max_bytes - len(suffix_bytes)
    if max_content_bytes_len <= 0:
        return TRUNCATION_SUFFIX.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')

    return content_bytes[:max_content_bytes_len].decode('utf-8', errors='ignore') + TRUNCATION_SUFFIX


def _normalize_mentions(mentions: Optional[Union[str, Sequence[str]]]) -> Sequence[str]:
    if mentions is None:
        return []
    if isinstance(mentions, str):
        return [mention.strip() for mention in mentions.split(',') if mention.strip()]
    return [mention.strip() for mention in mentions if mention.strip()]


def _append_markdown_mentions(content: str, mentions: Optional[Union[str, Sequence[str]]]) -> str:
    mention_list = _normalize_mentions(mentions)
    if not mention_list:
        return content
    return f'{content}\n\n{" ".join(f"<@{mention}>" for mention in mention_list)}'


def build_text_payload(
    content: str,
    mentioned_list: Optional[Sequence[str]] = None,
    mentioned_mobile_list: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    text: Dict[str, Any] = {'content': content}
    if mentioned_list is not None:
        text['mentioned_list'] = list(mentioned_list)
    if mentioned_mobile_list is not None:
        text['mentioned_mobile_list'] = list(mentioned_mobile_list)
    return {'msgtype': 'text', 'text': text}


def build_markdown_payload(content: str, msgtype: str = 'markdown') -> Dict[str, Any]:
    if msgtype not in ('markdown', 'markdown_v2'):
        raise ValueError('msgtype must be "markdown" or "markdown_v2"')
    return {'msgtype': msgtype, msgtype: {'content': _truncate_utf8(content)}}


def build_image_payload(base64_content: str, md5: str) -> Dict[str, Any]:
    return {'msgtype': 'image', 'image': {'base64': base64_content, 'md5': md5}}


def build_news_payload(articles: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {'msgtype': 'news', 'news': {'articles': [dict(article) for article in articles]}}


def build_file_payload(media_id: str) -> Dict[str, Any]:
    return {'msgtype': 'file', 'file': {'media_id': media_id}}


def build_voice_payload(media_id: str) -> Dict[str, Any]:
    return {'msgtype': 'voice', 'voice': {'media_id': media_id}}


def build_template_card_payload(template_card: Mapping[str, Any]) -> Dict[str, Any]:
    return {'msgtype': 'template_card', 'template_card': dict(template_card)}


def _response_status_code(response: Any) -> int:
    status_code = getattr(response, 'status', None)
    if status_code is None:
        status_code = response.getcode()
    return int(status_code)


def send_wecom_message(
    message: Union[str, Mapping[str, Any]],
    webhook_url: Optional[str] = None,
    msgtype: str = 'markdown',
    mentions: Optional[Union[str, Sequence[str]]] = None,
    timeout: float = 10,
) -> bool:
    """Send a WeCom group robot message.

    String messages are sent as markdown by default. Mapping messages are sent
    as already-built WeCom payloads.
    """
    webhook_url = _get_webhook_url(webhook_url)
    if not webhook_url or not _is_valid_url(webhook_url):
        logger.warning('WeCom notification failed: invalid webhook URL configured.')
        return False

    if isinstance(message, str):
        if not message.strip():
            return False
        if msgtype == 'text':
            payload = build_text_payload(message, mentioned_list=_normalize_mentions(mentions) or None)
        else:
            payload = build_markdown_payload(_append_markdown_mentions(message, mentions), msgtype=msgtype)
    else:
        payload = dict(message)

    request = Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = _response_status_code(response)
            if not 200 <= status_code < 300:
                logger.warning('WeCom notification failed: HTTP status %s', status_code)
                return False

            response_body = response.read().decode('utf-8')
            response_json = json.loads(response_body)
            errcode = response_json.get('errcode')
            if errcode != 0:
                logger.warning(
                    'WeCom notification failed: errcode=%s, errmsg=%s',
                    errcode,
                    response_json.get('errmsg'),
                )
                return False
            return True
    except HTTPError as e:
        logger.warning('WeCom notification failed: HTTP status %s', e.code)
    except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning('WeCom notification failed: %s', type(e).__name__)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning('WeCom notification failed: unexpected %s', type(e).__name__)
    return False
