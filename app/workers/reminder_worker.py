from __future__ import annotations
"""Reminder worker — prüft fällige Erinnerungen und schickt sie per Telegram."""
import logging
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.reminder import Reminder
from app.models.user import User
from app.integrations import telegram as tg
from app.services.reminder_service import ReminderService
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class ReminderWorker(BaseWorker):
    name = "reminder_worker"
    interval_seconds = 60

    async def tick(self) -> None:
        async with AsyncSessionLocal() as db:
            # Alle User mit fälligen Reminders finden
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(Reminder)
                .where(Reminder.remind_at <= now)
                .where(Reminder.is_sent == False)  # noqa
                .order_by(Reminder.remind_at)
                .limit(20)
            )
            due = list(result.scalars().all())
            if not due:
                return

            reminder_service = ReminderService(db)
            for reminder in due:
                try:
                    # User-ChatID holen
                    user_result = await db.execute(select(User).where(User.id == reminder.user_id))
                    user = user_result.scalar_one_or_none()
                    if not user:
                        continue

                    msg = "⏰ Erinnerung\n\n" + reminder.text
                    if reminder.source_email_id:
                        msg += f"\n\n(Bezug: E-Mail #{reminder.source_email_id})"

                    await tg.send_message(user.telegram_chat_id, msg)
                    await reminder_service.mark_sent(reminder.id)
                    logger.info("reminder_worker.sent", extra={"reminder_id": reminder.id})
                except Exception as e:
                    logger.error("reminder_worker.error", extra={"reminder_id": reminder.id, "error": str(e)})
