"""
Gmail integration — read-only access via Google Gmail API.
"""
import base64
import logging
import re
from email import message_from_bytes
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

logger = logging.getLogger(__name__)


def _get_credentials() -> Credentials:
    """Load or refresh Gmail OAuth credentials."""
    import os, json

    creds = None
    token_path = settings.GMAIL_TOKEN_JSON
    creds_path = settings.GMAIL_CREDENTIALS_JSON

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, settings.GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, settings.GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def _build_service():
    return build("gmail", "v1", credentials=_get_credentials(), cache_discovery=False)


def _decode_body(payload: dict) -> tuple[str, str]:
    """Extract plain-text and HTML body from message payload."""
    text, html = "", ""

    def _walk(part: dict) -> None:
        nonlocal text, html
        mime = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data", "")
        if mime == "text/plain" and body_data:
            text = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
        elif mime == "text/html" and body_data:
            html = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return text, html


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def list_unread_messages(max_results: int = None) -> list[dict[str, Any]]:
    """Return a list of unread Gmail messages with metadata and body."""
    max_results = max_results or settings.GMAIL_MAX_RESULTS
    try:
        service = _build_service()
        result = (
            service.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=max_results)
            .execute()
        )
        messages_meta = result.get("messages", [])
        messages = []

        for m in messages_meta:
            msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            headers = msg.get("payload", {}).get("headers", [])
            text, html = _decode_body(msg.get("payload", {}))

            messages.append(
                {
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "subject": _header(headers, "Subject"),
                    "sender": _header(headers, "From"),
                    "recipients": _header(headers, "To"),
                    "date": _header(headers, "Date"),
                    "body_text": text,
                    "body_html": html,
                    "snippet": msg.get("snippet", ""),
                }
            )
        logger.info("gmail.list_unread_messages", extra={"count": len(messages)})
        return messages

    except HttpError as e:
        logger.error("gmail.list_unread_messages.error", extra={"error": str(e)})
        raise


def mark_as_read(message_id: str) -> None:
    """Mark a Gmail message as read."""
    try:
        service = _build_service()
        service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
    except HttpError as e:
        logger.error("gmail.mark_as_read.error", extra={"message_id": message_id, "error": str(e)})
        raise
