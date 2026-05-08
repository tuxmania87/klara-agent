"""Unit tests for ToolExecutor."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.executor import ToolExecutor
from app.models.pending_action import ActionType, ActionStatus


@pytest.fixture
async def executor(db):
    return ToolExecutor(db=db, user_id=1)


class TestToolExecutor:

    async def test_unknown_tool_returns_error(self, executor):
        result = await executor.execute("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    async def test_queue_send_email_creates_pending_action(self, executor, db):
        from app.models.user import User
        # Create a user first
        user = User(telegram_chat_id=999, is_owner=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        executor.user_id = user.id

        result = await executor._queue_send_email(
            to=["test@example.com"],
            subject="Test Subject",
            body_text="Test body",
        )
        assert result["status"] == "pending_approval"
        assert "action_id" in result
        assert result["action_id"] > 0

    async def test_queue_calendar_event_creates_pending_action(self, executor, db):
        from app.models.user import User
        user = User(telegram_chat_id=1000, is_owner=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        executor.user_id = user.id

        result = await executor._queue_calendar_event(
            title="Team Meeting",
            start_iso="2025-01-15T10:00:00+01:00",
            end_iso="2025-01-15T11:00:00+01:00",
            description="Weekly sync",
        )
        assert result["status"] == "pending_approval"
        assert "action_id" in result

    async def test_read_gmail_ingests_emails(self, executor, db, mock_gmail):
        with patch("app.services.email_service.EmailService.ingest_gmail", new_callable=AsyncMock) as mock_ingest:
            from app.models.email import Email
            fake_email = Email(
                id=1, source="gmail", external_id="gmail:gmail_001",
                subject="Test Email", sender="sender@example.com"
            )
            mock_ingest.return_value = [fake_email]
            result = await executor._read_gmail(max_results=5)

        assert result["source"] == "gmail"
        assert result["count"] == 1
        assert result["emails"][0]["subject"] == "Test Email"

    async def test_list_calendar_events(self, executor):
        fake_events = [
            {
                "id": "evt1",
                "summary": "Doctor Appointment",
                "start": {"dateTime": "2025-01-20T09:00:00+01:00"},
                "location": "Main Street Clinic",
            }
        ]
        with patch(
            "app.integrations.google_calendar.list_events",
            return_value=fake_events,
        ):
            result = await executor._list_calendar_events(max_results=5)

        assert result["count"] == 1
        assert result["events"][0]["title"] == "Doctor Appointment"
