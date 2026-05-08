"""Pydantic schemas for pending actions."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.models.pending_action import ActionType, ActionStatus


class PendingActionOut(BaseModel):
    id: int
    action_type: ActionType
    status: ActionStatus
    description: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class ActionApprovalResponse(BaseModel):
    action_id: int
    status: ActionStatus
    message: str
