from __future__ import annotations
"""Note service — CRUD für Notizen."""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note

logger = logging.getLogger(__name__)


class NoteService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: int, content: str, title: str | None = None, tags: str | None = None) -> Note:
        note = Note(user_id=user_id, content=content, title=title, tags=tags)
        self.db.add(note)
        await self.db.commit()
        await self.db.refresh(note)
        logger.info("note_service.create", extra={"note_id": note.id, "user_id": user_id})
        return note

    async def list(self, user_id: int, limit: int = 20, tag: str | None = None) -> list[Note]:
        stmt = (
            select(Note)
            .where(Note.user_id == user_id)
            .order_by(Note.created_at.desc())
            .limit(limit)
        )
        if tag:
            stmt = stmt.where(Note.tags.ilike(f"%{tag}%"))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def search(self, user_id: int, query: str, limit: int = 10) -> list[Note]:
        stmt = (
            select(Note)
            .where(Note.user_id == user_id)
            .where(
                Note.content.ilike(f"%{query}%") | Note.title.ilike(f"%{query}%")
            )
            .order_by(Note.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, user_id: int, note_id: int) -> bool:
        result = await self.db.execute(
            select(Note).where(Note.id == note_id, Note.user_id == user_id)
        )
        note = result.scalar_one_or_none()
        if not note:
            return False
        await self.db.delete(note)
        await self.db.commit()
        logger.info("note_service.delete", extra={"note_id": note_id})
        return True

    async def update(self, user_id: int, note_id: int, content: str | None = None, title: str | None = None, tags: str | None = None) -> Note | None:
        result = await self.db.execute(
            select(Note).where(Note.id == note_id, Note.user_id == user_id)
        )
        note = result.scalar_one_or_none()
        if not note:
            return None
        if content is not None:
            note.content = content
        if title is not None:
            note.title = title
        if tags is not None:
            note.tags = tags
        await self.db.commit()
        await self.db.refresh(note)
        return note
