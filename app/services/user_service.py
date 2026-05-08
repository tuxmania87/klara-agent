"""User service — get or create users by Telegram chat ID."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(
        self,
        chat_id: int,
        username: str | None = None,
        full_name: str | None = None,
    ) -> User:
        result = await self.db.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_chat_id=chat_id,
                telegram_username=username,
                full_name=full_name,
                is_owner=(chat_id == settings.TELEGRAM_OWNER_CHAT_ID),
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def get_by_chat_id(self, chat_id: int) -> User | None:
        result = await self.db.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )
        return result.scalar_one_or_none()
