import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional, Sequence, Union

logger = logging.getLogger(__name__)

MAIL_SMTP_HOST_ENV = 'MAIL_SMTP_HOST'
MAIL_SMTP_PORT_ENV = 'MAIL_SMTP_PORT'
MAIL_USERNAME_ENV = 'MAIL_USERNAME'
MAIL_PASSWORD_ENV = 'MAIL_PASSWORD'
MAIL_FROM_ENV = 'MAIL_FROM'
MAIL_TO_ENV = 'MAIL_TO'
MAIL_USE_TLS_ENV = 'MAIL_USE_TLS'


def _normalize_addresses(addresses: Optional[Union[str, Sequence[str]]]) -> Sequence[str]:
    if addresses is None:
        return []
    if isinstance(addresses, str):
        return [address.strip() for address in addresses.split(',') if address.strip()]
    return [address.strip() for address in addresses if address.strip()]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ('0', 'false', 'no', 'off')


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning('Email notification failed: invalid %s=%s', name, value)
        return default


def _smtp_error_detail(error: smtplib.SMTPException) -> str:
    smtp_code = getattr(error, 'smtp_code', None)
    smtp_error = getattr(error, 'smtp_error', None)
    if isinstance(smtp_error, bytes):
        smtp_error = smtp_error.decode('utf-8', errors='replace')

    details = []
    if smtp_code is not None:
        details.append(f'code={smtp_code}')
    if smtp_error:
        details.append(f'message={smtp_error}')
    return ', '.join(details)


def build_email_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    subject: str,
    content: str,
    from_addr: str,
    to_addrs: Union[str, Sequence[str]],
    cc_addrs: Optional[Union[str, Sequence[str]]] = None,
    reply_to: Optional[str] = None,
) -> EmailMessage:
    """Build an HTML email message."""
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = from_addr
    message['To'] = ', '.join(_normalize_addresses(to_addrs))

    cc_list = _normalize_addresses(cc_addrs)
    if cc_list:
        message['Cc'] = ', '.join(cc_list)
    if reply_to:
        message['Reply-To'] = reply_to

    message.set_content(content, subtype='html')
    return message


def send_email_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    content: str,
    subject: str,
    to_addrs: Optional[Union[str, Sequence[str]]] = None,
    from_addr: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_tls: Optional[bool] = None,
    cc_addrs: Optional[Union[str, Sequence[str]]] = None,
    bcc_addrs: Optional[Union[str, Sequence[str]]] = None,
    reply_to: Optional[str] = None,
    timeout: float = 10,
) -> bool:
    """Send an HTML email notification via SMTP.

    The *content* argument is sent as ``text/html`` directly, so rich text and
    links should be written as HTML:

    .. code-block:: html

        <p>
          <b>Result:</b> passed<br>
          <a href="https://example.com/report">View report</a>
        </p>
    """
    smtp_host = smtp_host or os.getenv(MAIL_SMTP_HOST_ENV, '').strip()
    smtp_port = smtp_port if smtp_port is not None else _env_int(MAIL_SMTP_PORT_ENV, 25)
    username = username if username is not None else os.getenv(MAIL_USERNAME_ENV, '').strip()
    password = password if password is not None else os.getenv(MAIL_PASSWORD_ENV, '').strip()
    from_addr = from_addr or os.getenv(MAIL_FROM_ENV, '').strip() or username
    to_addrs = to_addrs if to_addrs is not None else os.getenv(MAIL_TO_ENV, '').strip()
    use_tls = use_tls if use_tls is not None else _env_bool(MAIL_USE_TLS_ENV, True)

    to_list = _normalize_addresses(to_addrs)
    cc_list = _normalize_addresses(cc_addrs)
    bcc_list = _normalize_addresses(bcc_addrs)
    if not smtp_host or not from_addr or not to_list:
        logger.warning('Email notification failed: smtp_host, from_addr, and to_addrs are required.')
        return False

    message = build_email_message(
        subject=subject,
        content=content,
        from_addr=from_addr,
        to_addrs=to_list,
        cc_addrs=cc_list,
        reply_to=reply_to,
    )
    recipients = list(to_list) + list(cc_list) + list(bcc_list)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message, to_addrs=recipients)
            return True
    except smtplib.SMTPException as e:
        detail = _smtp_error_detail(e)
        if detail:
            logger.warning('Email notification failed: %s (%s)', type(e).__name__, detail)
        else:
            logger.warning('Email notification failed: %s', type(e).__name__)
    except OSError as e:
        logger.warning('Email notification failed: %s', type(e).__name__)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning('Email notification failed: unexpected %s', type(e).__name__)
    return False
