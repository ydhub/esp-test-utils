# mypy: disable-error-code=no-untyped-def
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import Mock

import esptest.common.compat_typing as t
from esptest.notification import mail


class FakeSMTP:
    instances: t.List[t.Any] = []

    def __init__(self, host, port, timeout=0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.sent_message = None
        self.to_addrs = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message, to_addrs=None):
        self.sent_message = message
        self.to_addrs = to_addrs


class FailingSMTP(FakeSMTP):
    def send_message(self, message, to_addrs=None):
        raise OSError('smtp failed')


class SMTPDataErrorSMTP(FakeSMTP):
    def send_message(self, message, to_addrs=None):
        raise smtplib.SMTPDataError(554, b'5.2.0 SendAsDenied')


def test_build_email_message_sends_content_as_html():
    message = mail.build_email_message(
        subject='CI result',
        content='<p><a href="https://example.com">plain result</a></p>',
        from_addr='ci@example.com',
        to_addrs=['alice@example.com', 'bob@example.com'],
        cc_addrs=['carol@example.com'],
    )

    assert isinstance(message, EmailMessage)
    assert message['Subject'] == 'CI result'
    assert message['From'] == 'ci@example.com'
    assert message['To'] == 'alice@example.com, bob@example.com'
    assert message['Cc'] == 'carol@example.com'
    assert message.get_content_type() == 'text/html'
    assert message.get_content().strip() == '<p><a href="https://example.com">plain result</a></p>'


def test_send_email_message_uses_explicit_smtp_settings(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(mail.smtplib, 'SMTP', FakeSMTP)

    result = mail.send_email_message(
        content='build failed',
        subject='CI failed',
        to_addrs='alice@example.com,bob@example.com',
        from_addr='ci@example.com',
        smtp_host='smtp.example.com',
        smtp_port=2525,
        username='ci-user',
        password='secret',
        use_tls=True,
        bcc_addrs=['hidden@example.com'],
        timeout=3,
    )

    assert result is True
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == ('smtp.example.com', 2525, 3)
    assert smtp.started_tls is True
    assert smtp.logged_in == ('ci-user', 'secret')
    assert smtp.sent_message['Subject'] == 'CI failed'
    assert smtp.sent_message['From'] == 'ci@example.com'
    assert smtp.sent_message['To'] == 'alice@example.com, bob@example.com'
    assert smtp.sent_message.get_content().strip() == 'build failed'
    assert smtp.to_addrs == ['alice@example.com', 'bob@example.com', 'hidden@example.com']


def test_send_email_message_reads_environment(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(mail.smtplib, 'SMTP', FakeSMTP)
    monkeypatch.setenv('MAIL_SMTP_HOST', 'smtp.env.example.com')
    monkeypatch.setenv('MAIL_SMTP_PORT', '587')
    monkeypatch.setenv('MAIL_USERNAME', 'env-user')
    monkeypatch.setenv('MAIL_PASSWORD', 'env-secret')
    monkeypatch.setenv('MAIL_FROM', 'env-ci@example.com')
    monkeypatch.setenv('MAIL_TO', 'owner@example.com')
    monkeypatch.setenv('MAIL_USE_TLS', 'false')

    result = mail.send_email_message(content='build passed', subject='CI passed')

    assert result is True
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ('smtp.env.example.com', 587)
    assert smtp.started_tls is False
    assert smtp.logged_in == ('env-user', 'env-secret')
    assert smtp.sent_message['From'] == 'env-ci@example.com'
    assert smtp.sent_message['To'] == 'owner@example.com'


def test_send_email_message_returns_false_on_missing_required_config(monkeypatch):
    for env_name in (
        'MAIL_SMTP_HOST',
        'MAIL_SMTP_PORT',
        'MAIL_USERNAME',
        'MAIL_PASSWORD',
        'MAIL_FROM',
        'MAIL_TO',
        'MAIL_USE_TLS',
    ):
        monkeypatch.delenv(env_name, raising=False)
    smtp_mock = Mock()
    monkeypatch.setattr(mail.smtplib, 'SMTP', smtp_mock)

    assert mail.send_email_message(content='hello', subject='missing config') is False
    smtp_mock.assert_not_called()


def test_send_email_message_returns_false_on_smtp_error(monkeypatch):
    monkeypatch.setattr(mail.smtplib, 'SMTP', FailingSMTP)

    assert (
        mail.send_email_message(
            content='hello',
            subject='smtp error',
            to_addrs=['alice@example.com'],
            from_addr='ci@example.com',
            smtp_host='smtp.example.com',
        )
        is False
    )


def test_send_email_message_logs_smtp_data_error_detail(monkeypatch, caplog):
    monkeypatch.setattr(mail.smtplib, 'SMTP', SMTPDataErrorSMTP)

    assert (
        mail.send_email_message(
            content='hello',
            subject='smtp data error',
            to_addrs=['alice@example.com'],
            from_addr='ci@example.com',
            smtp_host='smtp.example.com',
        )
        is False
    )
    assert 'SMTPDataError' in caplog.text
    assert '554' in caplog.text
    assert '5.2.0 SendAsDenied' in caplog.text


def test_mail_module_can_run_as_script_without_shadowing_stdlib_email():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / 'esptest/notification/mail.py')],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ''
    assert result.stderr == ''
