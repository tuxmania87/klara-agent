"""Email model."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16))        # "gmail" | "mailcow"
    external_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(1024))
    sender: Mapped[str | None] = mapped_column(String(512))
    recipients: Mapped[str | None] = mapped_column(Text)   # JSON list
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    is_actionable: Mapped[bool] = mapped_column(Boolean, default=False)
    actionable_items: Mapped[str | None] = mapped_column(Text)  # JSON list
    is_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
