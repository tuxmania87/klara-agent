#!/usr/bin/env python3
"""
Google Calendar OAuth setup script.

Run this ONCE locally to generate gcal_token.json, then copy it to your
secrets/ directory before deploying.

Usage:
    python scripts/setup_gcal_auth.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import settings

SCOPES = settings.GCAL_SCOPES


def main():
    creds_path = settings.GCAL_CREDENTIALS_JSON
    token_path = settings.GCAL_TOKEN_JSON

    if not os.path.exists(creds_path):
        print(f"❌ Credentials file not found: {creds_path}")
        print("   Download it from Google Cloud Console → APIs & Services → Credentials")
        print("   Make sure Google Calendar API is enabled in your project.")
        sys.exit(1)

    print(f"📅 Starting Google Calendar OAuth flow...")
    print(f"   Scopes: {SCOPES}")
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)

    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"✅ Google Calendar token saved to: {token_path}")
    print(f"   Copy this file to your secrets/ directory.")


if __name__ == "__main__":
    main()
