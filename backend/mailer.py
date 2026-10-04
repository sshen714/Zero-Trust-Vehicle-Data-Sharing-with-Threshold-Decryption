"""Deliver one-time download codes through authenticated, encrypted SMTP."""
import os
import smtplib
import ssl
from email.message import EmailMessage

from .database import required_setting


class OtpDeliveryError(Exception):
    """SMTP configuration or delivery failed without exposing credentials."""


def send_download_otp(recipient: str, otp: str) -> None:
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
