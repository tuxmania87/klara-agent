"""Pydantic schemas for email-related request/response models."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class EmailSummary(BaseModel):
    id: int
    source: str
    subject: Optional[str]
    sender: Optional[str]
    received_at: Optional[datetime]
    summary: Optional[str]
    is_actionable: bool
    is_analyzed: bool

    class Config:
        from_attributes = True


class SendEmailRequest(BaseModel):
    to: list[str]
    subject: str
    body_text: str
    body_html: Optional[str] = None
    cc: Optional[list[str]] = None


class EmailListResponse(BaseModel):
    count: int
    emails: list[EmailSummary]
