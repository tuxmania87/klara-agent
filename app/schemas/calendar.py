"""Pydantic schemas for Google Calendar events."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class CalendarEventCreate(BaseModel):
    title: str
    start_iso: str          # ISO 8601
    end_iso: str
    description: str = ""
    location: str = ""
    timezone: str = "Europe/Berlin"


class CalendarEventOut(BaseModel):
    id: int
    google_event_id: Optional[str]
    title: str
    description: Optional[str]
    location: Optional[str]
    start_time: datetime
    end_time: datetime
    timezone: str
    created_at: datetime

    class Config:
        from_attributes = True
