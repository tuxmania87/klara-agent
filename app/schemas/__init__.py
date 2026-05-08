"""Pydantic schema models."""
from app.schemas.telegram import TelegramUpdate, TelegramMessage, TelegramCallbackQuery
from app.schemas.email import EmailSummary, SendEmailRequest, EmailListResponse
from app.schemas.action import PendingActionOut, ActionApprovalResponse
from app.schemas.calendar import CalendarEventCreate, CalendarEventOut

__all__ = [
    "TelegramUpdate", "TelegramMessage", "TelegramCallbackQuery",
    "EmailSummary", "SendEmailRequest", "EmailListResponse",
    "PendingActionOut", "ActionApprovalResponse",
    "CalendarEventCreate", "CalendarEventOut",
]
