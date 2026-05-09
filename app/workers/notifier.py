"""
Notification worker — benachrichtigt per Telegram nur bei relevanten Mails.
Sendet nur: urgent, needs_reply, needs_appointment, needs_followup.
Info-Mails und Newsletter werden still markiert.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, or_

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.email import Email
from app.integrations import telegram as tg
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)

# Nur diese Labels lösen eine Telegram-Benachrichtigung aus
NOTIFY_LABELS = {"urgent", "needs_reply", "needs_appointment", "needs_followup"}

# Mails die älter als X Stunden sind beim ersten Import still markieren
MAX_AGE_FOR_NOTIFICATION_HOURS = 24


class NotifierWorker(BaseWorker):
    name = "notifier"
    interval_seconds = settings.NOTIFICATION_POLL_INTERVAL_SECONDS

    async def tick(self) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Email)
                .where(Email.is_read == False)  # noqa: E712
                .order_by(Email.received_at.desc())
                .limit(20)
            )
            emails = list(result.scalars().all())

            if not emails:
                return

            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=MAX_AGE_FOR_NOTIFICATION_HOURS)
            notified_count = 0

            for email in emails:
                try:
                    # Alte Mails (z.B. beim ersten Import) still markieren
                    received = email.received_at
                    if received and received.tzinfo is None:
                        received = received.replace(tzinfo=timezone.utc)
                    if received and received < cutoff:
                        email.is_read = True
                        await db.commit()
                        logger.info("notifier.silently_marked_old", extra={"email_id": email.id})
                        continue

                    # Noch nicht triagiert → warten bis Analyzer fertig ist
                    if not email.is_analyzed:
                        continue

                    # Nur relevante Triage-Labels benachrichtigen
                    label = email.triage_label or ("needs_reply" if email.is_actionable else "info")
                    if label not in NOTIFY_LABELS:
                        # Still als gelesen markieren damit sie nicht ewig pending sind
                        email.is_read = True
                        await db.commit()
                        logger.info("notifier.silently_marked", extra={"email_id": email.id, "label": label})
                        continue

                    # Max 3 Benachrichtigungen pro Tick — Flut verhindern
                    if notified_count >= 3:
                        break

                    label_emoji = {
                        "urgent":             "🔴 DRINGEND",
                        "needs_reply":        "💬 Antwort nötig",
                        "needs_appointment":  "📅 Termin nötig",
                        "needs_followup":     "🔁 Follow-up",
                    }.get(label, "📬 Neu")

                    preview = email.triage_reason or email.summary or (email.body_text or "")[:200]
                    preview = preview[:300].replace("\n", " ").strip()

                    next_step = email.triage_reason or ""

                    msg = (
                        f"{label_emoji}\n"
                        f"Von: {email.sender or 'Unbekannt'}\n"
                        f"Betreff: {email.subject or '(kein Betreff)'}\n\n"
                        f"{preview}\n\n"
                        f"Mail-ID: {email.id}"
                    )

                    await tg.send_message(settings.TELEGRAM_OWNER_CHAT_ID, msg)
                    email.is_read = True
                    await db.commit()
                    notified_count += 1

                    logger.info(
                        "notifier.sent",
                        extra={"email_id": email.id, "subject": email.subject, "label": label},
                    )
                except Exception as e:
                    logger.error("notifier.error", extra={"email_id": email.id, "error": str(e)}, exc_info=True)
