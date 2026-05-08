#!/usr/bin/env python3
"""
Gmail OAuth setup script.

Run this ONCE locally to generate gmail_token.json, then copy it to your
secrets/ directory before deploying.

Usage:
    python scripts/setup_gmail_auth.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import settings

SCOPES = settings.GMAIL_SCOPES


def main():
    creds_path = settings.GMAIL_CREDENTIALS_JSON
    token_path = settings.GMAIL_TOKEN_JSON

    if not os.path.exists(creds_path):
        print(f"❌ Credentials file not found: {creds_path}")
        print("   Download it from Google Cloud Console → APIs & Services → Credentials")
        print("   (OAuth 2.0 Client ID → Desktop application)")
        sys.exit(1)

    print(f"🔐 Starting Gmail OAuth flow...")
    print(f"   Scopes: {SCOPES}")
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)

    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"✅ Gmail token saved to: {token_path}")
    print(f"   Copy this file to your secrets/ directory.")


if __name__ == "__main__":
    main()
