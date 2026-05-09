"""Reminder service — Erinnerungen erstellen und abfragen."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder

logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: int,
        text: str,
        remind_at: datetime,
        source_email_id: int | None = None,
        source_note_id: int | None = None,
    ) -> Reminder:
        reminder = Reminder(
            user_id=user_id,
            text=text,
            remind_at=remind_at,
            source_email_id=source_email_id,
            source_note_id=source_note_id,
        )
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)
        logger.info("reminder_service.create", extra={"reminder_id": reminder.id, "remind_at": str(remind_at)})
        return reminder

    async def get_due(self, user_id: int) -> list[Reminder]:
        """Alle fälligen, noch nicht gesendeten Reminders."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Reminder)
            .where(Reminder.user_id == user_id)
            .where(Reminder.remind_at <= now)
            .where(Reminder.is_sent == False)  # noqa
            .order_by(Reminder.remind_at)
        )
        return list(result.scalars().all())

    async def get_upcoming(self, user_id: int, limit: int = 10) -> list[Reminder]:
        """Noch ausstehende Reminders in der Zukunft."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Reminder)
            .where(Reminder.user_id == user_id)
            .where(Reminder.remind_at > now)
            .where(Reminder.is_sent == False)  # noqa
            .order_by(Reminder.remind_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_sent(self, reminder_id: int) -> None:
        result = await self.db.execute(select(Reminder).where(Reminder.id == reminder_id))
        reminder = result.scalar_one_or_none()
        if reminder:
            reminder.is_sent = True
            reminder.sent_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def delete(self, user_id: int, reminder_id: int) -> bool:
        result = await self.db.execute(
            select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id)
        )
        reminder = result.scalar_one_or_none()
        if not reminder:
            return False
        await self.db.delete(reminder)
        await self.db.commit()
        return True
