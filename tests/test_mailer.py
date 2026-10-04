"""SMTP transport checks; never send real email."""
import os
import unittest
from unittest.mock import patch
from backend.mailer import OtpDeliveryError, otp_recipient, send_download_otp


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.settings = dict(MAIL_PROVIDER='smtp', SMTP_HOST='smtp.example.test', SMTP_PORT='587',
            SMTP_SECURITY='starttls', SMTP_USERNAME='sender',
            SMTP_PASSWORD='test-password', SMTP_FROM='sender@example.test')

    def test_starttls_precedes_login_and_message_contains_code(self):
        with patch.dict(os.environ, self.settings), patch('backend.mailer.smtplib.SMTP') as smtp:
            client = smtp.return_value
            client.send_message.return_value = {}
            send_download_otp('owner@example.test', '123456')
            self.assertEqual([c[0] for c in client.method_calls], ['starttls','login','send_message'])
            message = client.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'owner@example.test')
            self.assertIn('123456', message.get_content())

    def test_ssl_uses_ssl_transport(self):
        with patch.dict(os.environ, {**self.settings,'SMTP_SECURITY':'ssl','SMTP_PORT':'465'}), patch('backend.mailer.smtplib.SMTP_SSL') as smtp:
            client = smtp.return_value
            client.send_message.return_value = {}
            send_download_otp('owner@example.test', '123456')
            client.starttls.assert_not_called()
            client.login.assert_called_once()

    def test_missing_settings_do_not_open_connection(self):
        with patch.dict(os.environ, {'MAIL_PROVIDER':'smtp','SMTP_HOST':''}), patch('backend.mailer.smtplib.SMTP') as smtp:
            with self.assertRaises(OtpDeliveryError):
                send_download_otp('owner@example.test', '123456')
            smtp.assert_not_called()

    def test_network_error_is_sanitized(self):
        with patch.dict(os.environ, self.settings), patch('backend.mailer.smtplib.SMTP', side_effect=OSError('private detail')):
            with self.assertRaises(OtpDeliveryError) as result:
                send_download_otp('owner@example.test','123456')
            self.assertNotIn('private detail', str(result.exception))


class RecipientTests(unittest.TestCase):
    def test_role_routing_and_account_fallback(self):
        settings = {'OTP_SUPERVISOR_A_EMAIL':'a@example.test',
                    'OTP_SUPERVISOR_B_EMAIL':'b@example.test',
                    'OTP_DEFAULT_EMAIL':'other@example.test'}
        with patch.dict(os.environ, settings):
            self.assertEqual(otp_recipient('supervisor_a','account@example.test'),'a@example.test')
            self.assertEqual(otp_recipient('supervisor_b','account@example.test'),'b@example.test')
            self.assertEqual(otp_recipient('owner','account@example.test'),'other@example.test')
        with patch.dict(os.environ, {'OTP_DEFAULT_EMAIL':''}):
            self.assertEqual(otp_recipient('owner','account@example.test'),'account@example.test')


class GmailTests(unittest.TestCase):
    def test_raw_message_and_recipient(self):
        import base64
        from email import message_from_bytes
        with patch.dict(os.environ, {'MAIL_PROVIDER':'gmail','GMAIL_SENDER':'sender@example.test'}), patch('backend.gmail.gmail_service') as service:
            send_download_otp('owner@example.test','123456')
            call = service.return_value.users.return_value.messages.return_value.send
            self.assertEqual(call.call_args.kwargs['userId'], 'me')
            message = message_from_bytes(base64.urlsafe_b64decode(call.call_args.kwargs['body']['raw']))
            self.assertEqual(message['To'], 'owner@example.test')
            self.assertIn('123456', message.get_payload(decode=True).decode())

    def test_missing_token_returns_delivery_error(self):
        with patch.dict(os.environ, {'MAIL_PROVIDER':'gmail','GMAIL_SENDER':'sender@example.test'}), patch('backend.gmail.gmail_service', side_effect=FileNotFoundError('secret path')):
            with self.assertRaises(OtpDeliveryError) as result:
                send_download_otp('owner@example.test','123456')
            self.assertNotIn('secret path',str(result.exception))
