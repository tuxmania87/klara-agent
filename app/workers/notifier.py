"""Notification worker — sends actionable email summaries to owner via Telegram."""
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
            # Find analyzed actionable emails that haven't been reported
            result = await db.execute(
                select(Email).where(
                    Email.is_actionable == True,  # noqa
                    Email.is_analyzed == True,
                    Email.is_read == False,
                ).limit(5)
            )
            emails = list(result.scalars().all())

            for email in emails:
                msg = (
                    f"📬 *Actionable Email Detected*\n"
                    f"From: {email.sender}\n"
                    f"Subject: {email.subject}\n\n"
                    f"*Summary:* {email.summary or 'No summary yet.'}\n\n"
                    f"Reply with your instructions to take action."
                )
                try:
                    await tg.send_message(settings.TELEGRAM_OWNER_CHAT_ID, msg)
                    email.is_read = True
                    await db.commit()
                    logger.info("notifier.sent", extra={"email_id": email.id})
                except Exception as e:
                    logger.error("notifier.error", extra={"email_id": email.id, "error": str(e)})
