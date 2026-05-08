"""
Telegram Bot integration — webhook-based messaging.
"""
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
TIMEOUT = httpx.Timeout(30.0)


async def send_message(
    chat_id: int,
    text: str,
    parse_mode: str = "Markdown",
    reply_markup: dict | None = None,
) -> dict[str, Any]:
    """
    Send a text message. Falls back to plain text if Markdown is rejected.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)

        # Retry as plain text if Markdown caused a 400
        if resp.status_code == 400 and parse_mode:
            logger.warning(
                "telegram.send_message.markdown_failed",
                extra={"chat_id": chat_id, "error": resp.text},
            )
            plain: dict[str, Any] = {"chat_id": chat_id, "text": text}
            if reply_markup:
                plain["reply_markup"] = reply_markup
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=plain)

        resp.raise_for_status()
        logger.info("telegram.send_message", extra={"chat_id": chat_id, "text_len": len(text)})
        return resp.json()


async def send_action_approval_prompt(
    chat_id: int,
    action_id: int,
    description: str,
) -> dict[str, Any]:
    text = (
        f"Pending Action #{action_id}\n\n"
        f"{description}\n\n"
        f"Do you approve this action?"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve_{action_id}"},
            {"text": "❌ Reject",  "callback_data": f"reject_{action_id}"},
        ]]
    }
    return await send_message(chat_id, text, parse_mode="", reply_markup=reply_markup)


async def answer_callback_query(callback_query_id: str, text: str = "") -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        await client.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )


async def get_file_url(file_id: str) -> str:
    """Resolve a Telegram file_id to a download URL."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        return f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"


async def download_file(file_id: str) -> bytes:
    """Download a Telegram file by file_id and return raw bytes."""
    url = await get_file_url(file_id)
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        logger.info("telegram.download_file", extra={"file_id": file_id, "bytes": len(resp.content)})
        return resp.content


async def set_webhook(webhook_url: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": webhook_url}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{TELEGRAM_API}/setWebhook", json=payload)
        resp.raise_for_status()
        return resp.json()


def parse_update(data: dict) -> dict[str, Any]:
    """
    Parse a Telegram update. Handles:
    - text messages
    - document attachments (PDF, etc.)
    - photo attachments
    - callback queries (inline keyboard)
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
        result["message_id"] = msg.get("message_id")
        result["text"] = msg.get("text", "") or msg.get("caption", "") or ""

        # Document attachment (PDF, DOCX, etc.)
        if "document" in msg:
            doc = msg["document"]
            result["attachment"] = {
                "type": "document",
                "file_id": doc["file_id"],
                "file_name": doc.get("file_name", "document"),
                "mime_type": doc.get("mime_type", "application/octet-stream"),
                "file_size": doc.get("file_size", 0),
            }

        # Photo attachment (highest resolution)
        elif "photo" in msg:
            photo = msg["photo"][-1]  # last = largest
            result["attachment"] = {
                "type": "photo",
                "file_id": photo["file_id"],
                "file_name": "photo.jpg",
                "mime_type": "image/jpeg",
                "file_size": photo.get("file_size", 0),
            }

    elif "callback_query" in data:
        cq = data["callback_query"]
        result["type"] = "callback_query"
        result["chat_id"] = cq["message"]["chat"]["id"]
        result["user_id"] = cq.get("from", {}).get("id")
        result["callback_query_id"] = cq["id"]
        result["callback_data"] = cq.get("data", "")
        result["message_id"] = cq["message"].get("message_id")

    return result
