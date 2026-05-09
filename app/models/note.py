"""Note model — user-created notes stored by the agent."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(String(512))     # komma-separiert
    category: Mapped[str | None] = mapped_column(String(32))  # task|idea|shopping|kids|case|tech|routine|template
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|done|archived
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(64))    # email_id, telegram, manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="notes")  # noqa
