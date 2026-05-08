#!/usr/bin/env python3
"""
Register the Telegram webhook with your bot.

Usage:
    python scripts/set_telegram_webhook.py https://yourdomain.com
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/set_telegram_webhook.py https://yourdomain.com")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    webhook_url = f"{base_url}/webhook/telegram"

    from app.integrations.telegram import set_webhook
    result = await set_webhook(webhook_url)

    if result.get("ok"):
        print(f"✅ Webhook registered: {webhook_url}")
        print(f"   Description: {result.get('description', '')}")
    else:
        print(f"❌ Failed to register webhook: {result}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
