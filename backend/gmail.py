"""Gmail API credentials for the locally authorized sending account."""
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ['https://www.googleapis.com/auth/gmail.send']


def gmail_path(setting: str, default: str) -> Path:
    path = Path(os.getenv(setting, default))
    return path if path.is_absolute() else ROOT / path


def gmail_service():
    credentials = Credentials.from_authorized_user_file(
        gmail_path('GMAIL_TOKEN_FILE', 'backend/gmail-token.json'), SCOPES,
    )
    if not credentials.has_scopes(SCOPES):
        raise ValueError('Gmail sending permission is missing')
    if not credentials.valid:
        if not credentials.refresh_token:
            raise ValueError('Gmail authorization is required')
        credentials.refresh(Request())
    return build('gmail', 'v1', credentials=credentials, cache_discovery=False)
