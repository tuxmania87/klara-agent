"""Track which email IDs have been processed to prevent duplicates."""
from datetime import datetime
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProcessedEmailId(Base):
    __tablename__ = "processed_email_ids"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), index=True)   # "gmail" | "mailcow"
    external_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
