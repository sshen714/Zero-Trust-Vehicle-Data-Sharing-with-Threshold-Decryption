"""Authorize Gmail sending once; no email is sent by this tool."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from backend.gmail import SCOPES, gmail_path


def main():
    load_dotenv(ROOT / 'backend/.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    credentials_path = gmail_path('GMAIL_CREDENTIALS_FILE', 'backend/gmail-credentials.json')
    token_path = gmail_path('GMAIL_TOKEN_FILE', 'backend/gmail-token.json')
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    credentials = flow.run_local_server(
        host='127.0.0.1', port=args.port, open_browser=False,
        timeout_seconds=300, access_type='offline', prompt='consent',
        login_hint=os.getenv('GMAIL_SENDER', ''),
        authorization_prompt_message='請用寄件帳號開啟以下網址完成授權：\n{url}',
        success_message='Gmail 授權已完成，可以關閉此頁面。',
    )
    if not credentials.refresh_token:
        raise RuntimeError('未取得 refresh token，請重新授權。')
    token_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = token_path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(credentials.to_json())
    temporary.replace(token_path)
    token_path.chmod(0o600)
    print('授權憑證已儲存；本次沒有寄出郵件。')


if __name__ == '__main__':
    main()
