"""
Mailcow API integration — list, read, and send emails via Mailcow REST API.
"""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0)


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": settings.MAILCOW_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _base() -> str:
    return settings.MAILCOW_API_URL.rstrip("/")


class MailcowClient:
    """Reusable async Mailcow API client."""

    async def list_messages(
        self,
        mailbox: str | None = None,
        folder: str = "INBOX",
        limit: int = 20,
        unread_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List messages from a Mailcow mailbox."""
        mailbox = mailbox or settings.MAILCOW_EMAIL_ADDRESS
        params: dict[str, Any] = {
            "mailbox": mailbox,
            "folder": folder,
            "limit": limit,
        }
        if unread_only:
            params["unseen"] = 1

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{_base()}/get/mailbox/messages",
                headers=_headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "mailcow.list_messages",
                extra={"mailbox": mailbox, "count": len(data)},
            )
            return data

    async def get_message(
        self, message_uid: str, mailbox: str | None = None
    ) -> dict[str, Any]:
        """Fetch a single message body by UID."""
        mailbox = mailbox or settings.MAILCOW_EMAIL_ADDRESS
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{_base()}/get/mailbox/message/{message_uid}",
                headers=_headers(),
                params={"mailbox": mailbox},
            )
            resp.raise_for_status()
            return resp.json()

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
        cc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an email via Mailcow.
        NOTE: Never called directly — always goes through pending_action approval.
        """
        payload: dict[str, Any] = {
            "from": settings.MAILCOW_EMAIL_ADDRESS,
            "to": to,
            "subject": subject,
            "text": body_text,
        }
        if body_html:
            payload["html"] = body_html
        if cc:
            payload["cc"] = cc
        if reply_to:
            payload["replyTo"] = reply_to

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{_base()}/send/email",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info("mailcow.send_email", extra={"to": to, "subject": subject})
            return result

    async def mark_as_read(self, message_uid: str, mailbox: str | None = None) -> None:
        mailbox = mailbox or settings.MAILCOW_EMAIL_ADDRESS
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{_base()}/edit/mailbox/flags",
                headers=_headers(),
                json={
                    "mailbox": mailbox,
                    "uid": message_uid,
                    "flags": {"add": ["\\Seen"]},
                },
            )
            resp.raise_for_status()


mailcow_client = MailcowClient()
