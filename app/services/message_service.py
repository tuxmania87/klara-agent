"""Message service — persist and retrieve Telegram conversation history."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


class MessageService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(
        self,
        user_id: int,
        telegram_message_id: int,
        role: str,
        content: str,
    ) -> Message:
        msg = Message(
            user_id=user_id,
            telegram_message_id=telegram_message_id,
            role=role,
            content=content,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def get_history(self, user_id: int, limit: int = 20) -> list[dict]:
        result = await self.db.execute(
            select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        return [{"role": m.role, "content": m.content} for m in messages]
