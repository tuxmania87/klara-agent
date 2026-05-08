"""
Pending action model — every write operation waits for user approval.
"""
import enum
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ActionType(str, enum.Enum):
    SEND_EMAIL = "send_email"
    CREATE_CALENDAR_EVENT = "create_calendar_event"
    DELETE_EMAIL = "delete_email"


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action_type: Mapped[ActionType] = mapped_column(String(64))
    status: Mapped[ActionStatus] = mapped_column(
        String(32), default=ActionStatus.PENDING, index=True
    )
    payload: Mapped[str] = mapped_column(Text)     # JSON blob
    description: Mapped[str] = mapped_column(Text)  # Human-readable summary
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    source_email_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="pending_actions")  # noqa
