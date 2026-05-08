"""Unit tests for ActionService."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.models.pending_action import ActionType, ActionStatus
from app.models.user import User
from app.services.action_service import ActionService


@pytest.fixture
async def user(db):
    u = User(telegram_chat_id=12345, is_owner=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.fixture
def action_service(db):
    return ActionService(db)


class TestActionService:

    async def test_create_action(self, action_service, user):
        action = await action_service.create_action(
            user_id=user.id,
            action_type=ActionType.SEND_EMAIL,
            payload={"to": ["x@y.com"], "subject": "Hi", "body_text": "Hello"},
            description="Send an email",
        )
        assert action.id is not None
        assert action.status == ActionStatus.PENDING
        assert action.action_type == ActionType.SEND_EMAIL

    async def test_reject_action(self, action_service, user):
        action = await action_service.create_action(
            user_id=user.id,
            action_type=ActionType.SEND_EMAIL,
            payload={"to": ["x@y.com"], "subject": "Hi", "body_text": "Hello"},
            description="Send an email",
        )
        await action_service.reject(action.id)

        from sqlalchemy import select
        from app.models.pending_action import PendingAction
        result = await action_service.db.execute(
            select(PendingAction).where(PendingAction.id == action.id)
        )
        updated = result.scalar_one()
        assert updated.status == ActionStatus.REJECTED
        assert updated.resolved_at is not None

    async def test_approve_and_execute_send_email(self, action_service, user):
        action = await action_service.create_action(
            user_id=user.id,
            action_type=ActionType.SEND_EMAIL,
            payload={
                "to": ["recipient@example.com"],
                "subject": "Test",
                "body_text": "Test body",
            },
            description="Send test email",
        )

        mock_client = AsyncMock()
        mock_client.send_email.return_value = {"status": "sent"}

        with patch("app.services.action_service.mailcow_client", mock_client):
            result = await action_service.approve_and_execute(action.id)

        assert "executed successfully" in result
        mock_client.send_email.assert_called_once()

    async def test_get_pending_for_user(self, action_service, user):
        await action_service.create_action(
            user_id=user.id,
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            payload={"title": "Meeting", "start_iso": "2025-01-15T10:00:00", "end_iso": "2025-01-15T11:00:00"},
            description="Create meeting",
        )
        pending = await action_service.get_pending_for_user(user.id)
        assert len(pending) >= 1

    async def test_double_approval_rejected(self, action_service, user):
        action = await action_service.create_action(
            user_id=user.id,
            action_type=ActionType.SEND_EMAIL,
            payload={"to": ["x@y.com"], "subject": "Hi", "body_text": "Hello"},
            description="Send an email",
        )
        await action_service.reject(action.id)
        # Trying to approve a rejected action should return error message
        result = await action_service.approve_and_execute(action.id)
        assert "already" in result
