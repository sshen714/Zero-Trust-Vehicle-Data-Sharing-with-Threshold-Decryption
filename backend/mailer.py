"""Deliver one-time download codes through authenticated, encrypted SMTP."""
import os
import smtplib
import ssl
import base64
from email.message import EmailMessage

from .database import required_setting


class OtpDeliveryError(Exception):
    """SMTP configuration or delivery failed without exposing credentials."""


def otp_recipient(role: str, account_email: str) -> str:
    """Resolve local testing recipients without changing account identities."""
    setting = {
        'supervisor_a': 'OTP_SUPERVISOR_A_EMAIL',
        'supervisor_b': 'OTP_SUPERVISOR_B_EMAIL',
    }.get(role, 'OTP_DEFAULT_EMAIL')
    return os.getenv(setting, '').strip() or account_email


def send_download_otp(recipient: str, otp: str) -> None:
    if os.getenv('MAIL_PROVIDER', 'smtp').strip().lower() == 'gmail':
        send_gmail_otp(recipient, otp)
        return
    try:
        host = required_setting('SMTP_HOST')
        username = required_setting('SMTP_USERNAME')
        password = required_setting('SMTP_PASSWORD')
        sender = required_setting('SMTP_FROM')
        security = os.getenv('SMTP_SECURITY', 'starttls').strip().lower()
        if security not in ('starttls', 'ssl'):
            raise ValueError('Invalid SMTP security')
        port = int(os.getenv('SMTP_PORT', '465' if security == 'ssl' else '587'))
        if not 1 <= port <= 65535:
            raise ValueError('Invalid SMTP port')
        message = EmailMessage()
        message['Subject'] = '車輛資料下載驗證碼'
        message['From'] = sender
        message['To'] = recipient
        message.set_content(
            f'您的車輛資料下載驗證碼為：{otp}\n\n'
            '驗證碼五分鐘內有效，僅限本次下載申請使用。\n'
            '若您沒有申請下載，請忽略此信。\n'
        )
        context = ssl.create_default_context()
        if security == 'ssl':
            client = smtplib.SMTP_SSL(host, port, timeout=10, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=10)
        with client:
            if security == 'starttls':
                client.starttls(context=context)
            client.login(username, password)
            refused = client.send_message(message)
            if refused:
                raise OtpDeliveryError()
    except (RuntimeError, ValueError, OSError, smtplib.SMTPException) as exc:
        raise OtpDeliveryError('OTP email delivery failed') from exc


def send_gmail_otp(recipient: str, otp: str) -> None:
    from .gmail import gmail_service
    from google.auth.exceptions import GoogleAuthError
    from googleapiclient.errors import HttpError

    try:
        message = EmailMessage()
        message['Subject'] = '車輛資料下載驗證碼'
        message['From'] = required_setting('GMAIL_SENDER')
        message['To'] = recipient
        message.set_content(
            f'您的車輛資料下載驗證碼為：{otp}\n\n'
            '驗證碼五分鐘內有效，僅限本次下載申請使用。\n'
            '若您沒有申請下載，請忽略此信。\n'
        )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        gmail_service().users().messages().send(
            userId='me', body={'raw': raw},
        ).execute()
    except (GoogleAuthError, HttpError, OSError, ValueError, RuntimeError) as exc:
        raise OtpDeliveryError('OTP email delivery failed') from exc
