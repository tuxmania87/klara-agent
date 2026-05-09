"""
Mailcow integration:
  - Reading emails via IMAP (aioimaplib)
  - Sending emails via SMTP (aiosmtplib)

Verbose debug logging shows exactly which host/user/port is used for each connection.
"""
import asyncio
import email
import logging
import ssl
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from typing import Any

import aioimaplib
import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _decode_header_value(raw: str) -> str:
    parts = decode_header(raw or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    text, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if "attachment" in str(part.get("Content-Disposition", "")):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/plain" and not text:
                text = decoded
            elif ct == "text/html" and not html:
                html = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
    return text, html


# ── IMAP — reading ────────────────────────────────────────────────────────────

class MailcowIMAPClient:
    """Async IMAP client for reading emails from a Mailcow mailbox."""

    def __init__(self):
        self.host     = settings.MAILCOW_IMAP_HOST
        self.port     = settings.MAILCOW_IMAP_PORT
        self.username = settings.MAILCOW_EMAIL_ADDRESS
        self.password = settings.MAILCOW_IMAP_PASSWORD
        self.use_ssl  = settings.MAILCOW_IMAP_SSL

    async def _connect(self) -> aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL:
        logger.info(
            "mailcow.imap.connecting",
            extra={
                "host":     self.host,
                "port":     self.port,
                "username": self.username,
                "ssl":      self.use_ssl,
            },
        )
        if self.use_ssl:
            client = aioimaplib.IMAP4_SSL(host=self.host, port=self.port)
        else:
            client = aioimaplib.IMAP4(host=self.host, port=self.port)

        await client.wait_hello_from_server()

        logger.info(
            "mailcow.imap.login_attempt",
            extra={"host": self.host, "username": self.username},
        )
        resp = await client.login(self.username, self.password)
        if resp.result != "OK":
            logger.error(
                "mailcow.imap.login_failed",
                extra={"host": self.host, "username": self.username, "response": str(resp.lines)},
            )
            raise ConnectionError(f"IMAP login failed for {self.username}@{self.host}:{self.port} — {resp.lines}")

        logger.info(
            "mailcow.imap.login_ok",
            extra={"host": self.host, "username": self.username},
        )
        return client

    async def list_messages(
        self,
        folder: str = "INBOX",
        limit: int = 20,
        unseen_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch unread messages. Returns normalized dicts."""
        client = await self._connect()

        resp = await client.select(folder)
        if resp.result != "OK":
            await client.logout()
            raise ConnectionError(f"IMAP SELECT '{folder}' failed: {resp.lines}")

        search_criteria = "UNSEEN" if unseen_only else "ALL"
        # Regular SEARCH returns sequence numbers (UID SEARCH not supported by all servers)
        resp = await client.search(search_criteria)
        logger.info(
            "mailcow.imap.search_raw",
            extra={"result": resp.result, "lines_repr": str(resp.lines)[:300]},
        )
        if resp.result != "OK":
            await client.logout()
            return []

        # aioimaplib gibt bei SEARCH die IDs unterschiedlich zurück:
        # Entweder als b'1 2 3' in lines[0], oder als ['1', '2', '3'] direkt,
        # oder als leeres b'' wenn keine Treffer. Wir probieren alle Varianten.
        raw_ids = ""
        for item in resp.lines:
            if isinstance(item, bytes):
                decoded = item.decode(errors="replace").strip()
                if decoded:
                    raw_ids = decoded
                    break
            elif isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    raw_ids = stripped
                    break
            elif isinstance(item, (list, tuple)):
                # Manchmal kommt eine Liste von IDs direkt
                raw_ids = " ".join(str(x) for x in item)
                break

        seq_list = [u for u in raw_ids.strip().split() if u.strip().isdigit()]

        if not seq_list:
            await client.logout()
            logger.info("mailcow.imap.list_messages", extra={"count": 0, "folder": folder})
            return []

        # Take the most recent `limit` sequence numbers
        seq_list = seq_list[-limit:]
        messages = []

        for seq in seq_list:
            try:
                # BODY.PEEK[] does NOT set \Seen — stable read without side effects
                # We also fetch UID so we can use it as a stable external_id
                resp = await client.fetch(seq, "(UID BODY.PEEK[])")
                if resp.result != "OK":
                    continue

                raw_email = None
                uid_str = str(seq.decode() if isinstance(seq, bytes) else seq)  # fallback
                for line in resp.lines:
                    if isinstance(line, bytes):
                        # Try to extract UID from the FETCH response line e.g. b'1 FETCH (UID 42 ...'
                        import re
                        m = re.search(rb"UID (\d+)", line)
                        if m:
                            uid_str = m.group(1).decode()
                        if len(line) > 100:
                            raw_email = line
                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                text, html = _extract_body(msg)
                subject    = _decode_header_value(msg.get("Subject", ""))
                sender     = _decode_header_value(msg.get("From", ""))
                recipients = _decode_header_value(msg.get("To", ""))
                date_str   = msg.get("Date", "")

                received_at = None
                if date_str:
                    try:
                        received_at = parsedate_to_datetime(date_str).isoformat()
                    except Exception:
                        pass

                messages.append({
                    "id":           uid_str,
                    "subject":      subject,
                    "sender":       sender,
                    "recipients":   recipients,
                    "date":         date_str,
                    "received_at":  received_at,
                    "body_text":    text,
                    "body_html":    html,
                    "snippet":      text[:200] if text else "",
                })
            except Exception as e:
                logger.error(
                    "mailcow.imap.fetch_error",
                    extra={"seq": str(seq), "error": str(e)},
                )

        await client.logout()
        logger.info("mailcow.imap.list_messages", extra={"count": len(messages), "folder": folder})
        return messages

    async def mark_as_read(self, uid: str, folder: str = "INBOX") -> None:
        client = await self._connect()
        await client.select(folder)
        # UID STORE for stable addressing
        await client.uid("store", uid, "+FLAGS", "\\Seen")
        await client.logout()
        logger.info("mailcow.imap.mark_read", extra={"uid": uid})


mailcow_imap_client = MailcowIMAPClient()


# ── SMTP — sending ────────────────────────────────────────────────────────────

async def send_email(
    to: list[str],
    subject: str,
    body_text: str,
    body_html: str | None = None,
    cc: list[str] | None = None,
    reply_to: str | None = None,
    from_addr: str | None = None,   # override sender display name/address
) -> dict[str, Any]:
    """
    Send email via SMTP (aiosmtplib).
    Always called through pending_action approval — never directly.
    """
    host      = settings.MAILCOW_SMTP_HOST
    port      = settings.MAILCOW_SMTP_PORT
    username  = settings.MAILCOW_EMAIL_ADDRESS
    password  = settings.MAILCOW_SMTP_PASSWORD
    use_tls   = settings.MAILCOW_SMTP_TLS
    from_addr = from_addr or username

    logger.info(
        "mailcow.smtp.send_attempt",
        extra={
            "host":     host,
            "port":     port,
            "username": username,
            "use_tls":  use_tls,
            "to":       to,
            "subject":  subject,
        },
    )

    # Build MIME message
    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEText(body_text, "plain", "utf-8")

    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to

    all_recipients = to + (cc or [])

    try:
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = True
        tls_context.verify_mode = ssl.CERT_REQUIRED

        if use_tls:
            # Port 465 — implicit TLS
            smtp = aiosmtplib.SMTP(
                hostname=host,
                port=port,
                use_tls=True,
                tls_context=tls_context,
            )
            await smtp.connect()
            await smtp.login(username, password)
            await smtp.send_message(msg)
            await smtp.quit()
        else:
            # Port 587 — STARTTLS
            smtp = aiosmtplib.SMTP(
                hostname=host,
                port=port,
                use_tls=False,
            )
            await smtp.connect()
            await smtp.starttls(tls_context=tls_context)
            await smtp.login(username, password)
            await smtp.send_message(msg)
            await smtp.quit()

        logger.info(
            "mailcow.smtp.send_ok",
            extra={"host": host, "username": username, "to": to, "subject": subject},
        )
        return {"status": "sent", "to": to, "subject": subject}

    except Exception as e:
        logger.error(
            "mailcow.smtp.send_failed",
            extra={"host": host, "port": port, "username": username, "error": str(e)},
        )
        raise


# ── Backwards compatibility ───────────────────────────────────────────────────

class MailcowClient:
    async def send_email(self, **kwargs):
        return await send_email(**kwargs)


mailcow_client = MailcowClient()
