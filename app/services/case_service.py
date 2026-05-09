from __future__ import annotations
"""Case service — Chronologie für laufende Fälle."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case, CaseEvent

logger = logging.getLogger(__name__)


class CaseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: int, title: str, description: str | None = None) -> Case:
        case = Case(user_id=user_id, title=title, description=description)
        self.db.add(case)
        await self.db.commit()
        await self.db.refresh(case)
        logger.info("case_service.create", extra={"case_id": case.id, "title": title})
        return case

    async def list(self, user_id: int, status: str | None = None, limit: int = 20) -> list[Case]:
        stmt = select(Case).where(Case.user_id == user_id).order_by(Case.updated_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Case.status == status)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_with_events(self, user_id: int, case_id: int) -> Case | None:
        result = await self.db.execute(
            select(Case).where(Case.id == case_id, Case.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def add_event(
        self,
        case_id: int,
        description: str,
        happened_at: datetime | None = None,
        source: str | None = None,
        involved: str | None = None,
        open_questions: str | None = None,
    ) -> CaseEvent:
        event = CaseEvent(
            case_id=case_id,
            description=description,
            happened_at=happened_at or datetime.now(timezone.utc),
            source=source,
            involved=involved,
            open_questions=open_questions,
        )
        self.db.add(event)
        # Aktualisiere updated_at auf Case
        result = await self.db.execute(select(Case).where(Case.id == case_id))
        case = result.scalar_one_or_none()
        if case:
            case.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def update_status(self, user_id: int, case_id: int, status: str, next_step: str | None = None) -> Case | None:
        result = await self.db.execute(
            select(Case).where(Case.id == case_id, Case.user_id == user_id)
        )
        case = result.scalar_one_or_none()
        if not case:
            return None
        case.status = status
        if next_step is not None:
            case.next_step = next_step
        case.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return case

    async def get_events(self, case_id: int) -> list[CaseEvent]:
        result = await self.db.execute(
            select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.happened_at)
        )
        return list(result.scalars().all())
