"""User model."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(128))
    full_name: Mapped[str | None] = mapped_column(String(256))
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(back_populates="user")  # noqa
    pending_actions: Mapped[list["PendingAction"]] = relationship(back_populates="user")  # noqa
    notes: Mapped[list["Note"]] = relationship(back_populates="user")  # noqa
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="user")  # noqa
    cases: Mapped[list["Case"]] = relationship(back_populates="user")  # noqa
