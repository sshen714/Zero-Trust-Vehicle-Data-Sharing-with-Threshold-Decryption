"""SMTP transport checks; never send real email."""
import os
import unittest
from unittest.mock import patch
from backend.mailer import OtpDeliveryError, send_download_otp


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.settings = dict(SMTP_HOST='smtp.example.test', SMTP_PORT='587',
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
        with patch.dict(os.environ, {'SMTP_HOST':''}), patch('backend.mailer.smtplib.SMTP') as smtp:
            with self.assertRaises(OtpDeliveryError):
                send_download_otp('owner@example.test', '123456')
            smtp.assert_not_called()

    def test_network_error_is_sanitized(self):
        with patch.dict(os.environ, self.settings), patch('backend.mailer.smtplib.SMTP', side_effect=OSError('private detail')):
            with self.assertRaises(OtpDeliveryError) as result:
                send_download_otp('owner@example.test','123456')
            self.assertNotIn('private detail', str(result.exception))
