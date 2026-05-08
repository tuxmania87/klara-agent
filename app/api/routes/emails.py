"""
REST endpoints for browsing and managing stored emails.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.email import Email
from app.schemas.email import EmailSummary, EmailListResponse
from app.services.email_service import EmailService

router = APIRouter()


@router.get("", response_model=EmailListResponse)
async def list_emails(
    source: str | None = Query(None, description="Filter by source: gmail | mailcow"),
    actionable_only: bool = Query(False),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
) -> EmailListResponse:
    stmt = select(Email).order_by(Email.received_at.desc()).limit(limit)
    if source:
        stmt = stmt.where(Email.source == source)
    if actionable_only:
        stmt = stmt.where(Email.is_actionable == True)  # noqa

    result = await db.execute(stmt)
    emails = list(result.scalars().all())
    return EmailListResponse(
        count=len(emails),
        emails=[EmailSummary.model_validate(e) for e in emails],
    )


@router.get("/{email_id}", response_model=EmailSummary)
async def get_email(email_id: int, db: AsyncSession = Depends(get_db)) -> EmailSummary:
    svc = EmailService(db)
    email = await svc.get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return EmailSummary.model_validate(email)


@router.post("/{email_id}/summarize")
async def summarize_email(email_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    svc = EmailService(db)
    email = await svc.get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    summary = await svc.summarize_email(email)
    return {"email_id": email_id, "summary": summary}


@router.post("/ingest/gmail")
async def trigger_gmail_ingest(db: AsyncSession = Depends(get_db)) -> dict:
    """Manually trigger a Gmail ingestion (useful for testing)."""
    svc = EmailService(db)
    new_emails = await svc.ingest_gmail()
    return {"new_emails": len(new_emails)}


@router.post("/ingest/mailcow")
async def trigger_mailcow_ingest(db: AsyncSession = Depends(get_db)) -> dict:
    """Manually trigger a Mailcow ingestion."""
    svc = EmailService(db)
    new_emails = await svc.ingest_mailcow()
    return {"new_emails": len(new_emails)}
