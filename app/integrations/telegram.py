"""
Telegram Bot integration — webhook-based messaging.
"""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
TIMEOUT = httpx.Timeout(15.0)


async def send_message(
    chat_id: int,
    text: str,
    parse_mode: str = "Markdown",
    reply_markup: dict | None = None,
) -> dict[str, Any]:
    """Send a text message to a Telegram chat."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "telegram.send_message",
            extra={"chat_id": chat_id, "text_len": len(text)},
        )
        return data


async def send_action_approval_prompt(
    chat_id: int,
    action_id: int,
    description: str,
) -> dict[str, Any]:
    """Send a message asking for approval with inline keyboard buttons."""
    text = (
        f"⏳ *Pending Action #{action_id}*\n\n"
        f"{description}\n\n"
        f"Do you approve this action?"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve_{action_id}"},
                {"text": "❌ Reject", "callback_data": f"reject_{action_id}"},
            ]
        ]
    }
    return await send_message(chat_id, text, reply_markup=reply_markup)


async def answer_callback_query(callback_query_id: str, text: str = "") -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        await client.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )


async def set_webhook(webhook_url: str) -> dict[str, Any]:
    """Register the webhook URL with Telegram."""
    payload: dict[str, Any] = {"url": webhook_url}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{TELEGRAM_API}/setWebhook", json=payload)
        resp.raise_for_status()
        return resp.json()


def parse_update(data: dict) -> dict[str, Any]:
    """
    Parse a Telegram update into a normalized dict with keys:
    type, chat_id, user_id, text, callback_query_id, callback_data, message_id
    """
    result: dict[str, Any] = {}

    if "message" in data:
        msg = data["message"]
        result["type"] = "message"
        result["chat_id"] = msg["chat"]["id"]
        result["user_id"] = msg.get("from", {}).get("id")
        result["username"] = msg.get("from", {}).get("username")
        result["full_name"] = (
            f"{msg.get('from', {}).get('first_name', '')} "
            f"{msg.get('from', {}).get('last_name', '')}".strip()
        )
        result["text"] = msg.get("text", "")
        result["message_id"] = msg.get("message_id")

    elif "callback_query" in data:
        cq = data["callback_query"]
        result["type"] = "callback_query"
        result["chat_id"] = cq["message"]["chat"]["id"]
        result["user_id"] = cq.get("from", {}).get("id")
        result["callback_query_id"] = cq["id"]
        result["callback_data"] = cq.get("data", "")
        result["message_id"] = cq["message"].get("message_id")

    return result
