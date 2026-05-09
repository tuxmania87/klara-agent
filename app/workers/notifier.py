"""
Notification worker — notifies owner via Telegram when new emails arrive.
Runs every 30 seconds, sends a summary for every email not yet notified.
"""
import logging

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.email import Email
from app.integrations import telegram as tg
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class NotifierWorker(BaseWorker):
    name = "notifier"
    interval_seconds = settings.NOTIFICATION_POLL_INTERVAL_SECONDS

    async def tick(self) -> None:
        async with AsyncSessionLocal() as db:
            # Find ALL emails not yet notified (is_read = False means "not yet telegram-notified")
            # We notify for every email, not just actionable ones.
            # The agent can then decide what to do.
            result = await db.execute(
                select(Email)
                .where(Email.is_read == False)  # noqa: E712
                .order_by(Email.received_at.desc())
                .limit(5)
            )
            emails = list(result.scalars().all())

            if not emails:
                return

            for email in emails:
                try:
                    # Build message — use summary if analyzed, snippet if not
                    preview = email.summary or email.body_text or ""
                    preview = preview[:300].replace("\n", " ").strip()

                    actionable_tag = " [ACTION NEEDED]" if email.is_actionable else ""

                    msg = (
                        "New Email" + actionable_tag + "\n"
                        "From: " + (email.sender or "Unknown") + "\n"
                        "Subject: " + (email.subject or "(no subject)") + "\n\n"
                        + (preview or "(no preview available)")
                        + "\n\nReply with instructions if you want me to act on this."
                    )

                    await tg.send_message(settings.TELEGRAM_OWNER_CHAT_ID, msg)

                    # Mark as notified
                    email.is_read = True
                    await db.commit()

                    logger.info(
                        "notifier.sent",
                        extra={
                            "email_id": email.id,
                            "subject": email.subject,
                            "is_actionable": email.is_actionable,
                        },
                    )
                except Exception as e:
                    logger.error(
                        "notifier.error",
                        extra={"email_id": email.id, "error": str(e)},
                        exc_info=True,
                    )
