"""
End-to-end test: Telegram message → Agent → Tool calls → Approval → Execution.

This test verifies the complete flow without any real external API calls.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.models.user import User
from app.models.pending_action import ActionStatus, ActionType
from app.agent.orchestrator import Agent
from app.services.action_service import ActionService
from app.services.user_service import UserService


OWNER_CHAT_ID = 12345


@pytest.fixture
async def owner_user(db):
    svc = UserService(db)
    return await svc.get_or_create(
        chat_id=OWNER_CHAT_ID,
        username="testowner",
        full_name="Test Owner",
    )


# ─── Scenario 1: Simple email read ───────────────────────────────────────────

class TestAgentEmailReadFlow:

    async def test_read_emails_no_approval_needed(self, db, owner_user):
        """
        User asks to read emails.
        Gemini calls read_gmail_messages.
        Agent replies with email list.
        No pending actions created.
        """
        fake_emails = [
            {
                "id": 1,
                "subject": "Invoice #999",
                "sender": "billing@vendor.com",
                "snippet": "Your invoice is due on Friday.",
                "received_at": "2025-01-13T10:00:00",
            }
        ]

        gemini_chat = MagicMock()

        # First call: Gemini requests tool call
        # Second call (after tool result): Gemini returns final text
        gemini_responses = [
            ("", [{"name": "read_gmail_messages", "args": {"max_results": 5}}]),
            ("📬 Found 1 unread email:\n\n**Invoice #999** from billing@vendor.com\nDue Friday.", []),
        ]
        call_count = 0

        def mock_send_message(chat, text):
            nonlocal call_count
            resp = gemini_responses[0]
            call_count += 1
            return resp

        def mock_tool_result(chat, tool_name, result):
            return gemini_responses[1]

        with (
            patch("app.agent.orchestrator.gemini_agent") as mock_gemini,
            patch("app.services.email_service.EmailService.ingest_gmail", new_callable=AsyncMock) as mock_ingest,
            patch("app.integrations.telegram.send_message", new_callable=AsyncMock) as mock_tg,
            patch("app.integrations.telegram.send_action_approval_prompt", new_callable=AsyncMock) as mock_approval,
        ):
            mock_gemini.build_chat.return_value = gemini_chat
            mock_gemini.send_message.side_effect = mock_send_message
            mock_gemini.send_tool_result.side_effect = mock_tool_result

            # Return a fake email model
            from app.models.email import Email
            fake_email_model = Email(
                id=1, source="gmail", external_id="gmail:999",
                subject="Invoice #999", sender="billing@vendor.com",
                body_text="Your invoice is due on Friday."
            )
            mock_ingest.return_value = [fake_email_model]

            agent = Agent(db)
            await agent.handle_message(OWNER_CHAT_ID, "Check my Gmail", message_id=1)

        # Telegram should have sent the summary
        mock_tg.assert_called_once()
        sent_text = mock_tg.call_args[0][1]
        assert "Invoice" in sent_text

        # No approval prompts — reading is a safe operation
        mock_approval.assert_not_called()


# ─── Scenario 2: Calendar event creation with approval ───────────────────────

class TestAgentCalendarApprovalFlow:

    async def test_create_calendar_event_requires_approval(self, db, owner_user):
        """
        User asks to create a calendar event.
        Gemini calls create_google_calendar_event.
        A pending action is created.
        Agent sends approval prompt.
        User approves → event is created.
        """
        gemini_chat = MagicMock()

        event_args = {
            "title": "Doctor Appointment",
            "start_iso": "2025-01-20T09:00:00+01:00",
            "end_iso": "2025-01-20T10:00:00+01:00",
            "description": "Annual checkup",
            "location": "Munich Medical Center",
        }

        with (
            patch("app.agent.orchestrator.gemini_agent") as mock_gemini,
            patch("app.integrations.telegram.send_message", new_callable=AsyncMock) as mock_tg,
            patch("app.integrations.telegram.send_action_approval_prompt", new_callable=AsyncMock) as mock_approval,
        ):
            mock_approval.return_value = {"ok": True, "result": {"message_id": 77}}
            mock_gemini.build_chat.return_value = gemini_chat
            mock_gemini.send_message.return_value = (
                "",
                [{"name": "create_google_calendar_event", "args": event_args}]
            )
            mock_gemini.send_tool_result.return_value = (
                "I've queued a calendar event for *Doctor Appointment* on Jan 20 at 9:00 AM. Please approve it.",
                []
            )

            agent = Agent(db)
            await agent.handle_message(
                OWNER_CHAT_ID,
                "Add Doctor Appointment on Jan 20 at 9am to my calendar",
                message_id=2,
            )

        # Approval prompt must have been sent
        mock_approval.assert_called_once()
        approval_call = mock_approval.call_args
        assert approval_call.kwargs["chat_id"] == OWNER_CHAT_ID
        assert "Doctor Appointment" in approval_call.kwargs["description"]

        # Now simulate the user approving
        action_svc = ActionService(db)
        pending = await action_svc.get_all_pending()
        assert len(pending) == 1
        assert pending[0].action_type == ActionType.CREATE_CALENDAR_EVENT

        with (
            patch("app.integrations.google_calendar.create_event") as mock_create,
            patch("app.integrations.telegram.send_message", new_callable=AsyncMock) as mock_tg2,
            patch("app.integrations.telegram.answer_callback_query", new_callable=AsyncMock),
        ):
            mock_create.return_value = {"id": "gcal_event_001", "summary": "Doctor Appointment"}

            agent = Agent(db)
            await agent.handle_approval(
                OWNER_CHAT_ID,
                f"approve_{pending[0].id}",
                "cq_001",
            )

            mock_create.assert_called_once()
            create_kwargs = mock_create.call_args
            assert create_kwargs.kwargs["title"] == "Doctor Appointment" or \
                   create_kwargs.args[0] == "Doctor Appointment"

        # Verify action is now EXECUTED
        from sqlalchemy import select
        from app.models.pending_action import PendingAction
        result = await db.execute(
            select(PendingAction).where(PendingAction.id == pending[0].id)
        )
        action = result.scalar_one()
        assert action.status == ActionStatus.EXECUTED


# ─── Scenario 3: Rejection flow ──────────────────────────────────────────────

class TestAgentRejectionFlow:

    async def test_reject_send_email_action(self, db, owner_user):
        """
        Agent queues a send-email action.
        User rejects → action stays rejected, email is never sent.
        """
        action_svc = ActionService(db)
        action = await action_svc.create_action(
            user_id=owner_user.id,
            action_type=ActionType.SEND_EMAIL,
            payload={
                "to": ["boss@company.com"],
                "subject": "Resignation Letter",
                "body_text": "Dear Boss, I quit...",
            },
            description="📧 Send Email\nTo: boss@company.com\nSubject: Resignation Letter",
        )

        with (
            patch("app.integrations.mailcow.mailcow_client.send_email", new_callable=AsyncMock) as mock_send,
            patch("app.integrations.telegram.send_message", new_callable=AsyncMock),
            patch("app.integrations.telegram.answer_callback_query", new_callable=AsyncMock),
        ):
            agent = Agent(db)
            await agent.handle_approval(
                OWNER_CHAT_ID,
                f"reject_{action.id}",
                "cq_002",
            )

            # Email must NOT be sent
            mock_send.assert_not_called()

        from sqlalchemy import select
        from app.models.pending_action import PendingAction
        result = await db.execute(
            select(PendingAction).where(PendingAction.id == action.id)
        )
        updated = result.scalar_one()
        assert updated.status == ActionStatus.REJECTED


# ─── Scenario 4: Multi-tool chaining ─────────────────────────────────────────

class TestAgentMultiToolFlow:

    async def test_read_then_summarize_chain(self, db, owner_user):
        """
        Gemini chains two tool calls:
        1. read_gmail_messages
        2. summarize_email
        Then returns a final summary to the user.
        """
        from app.models.email import Email

        fake_email = Email(
            id=42, source="gmail", external_id="gmail:chain001",
            subject="Q4 Report", sender="cfo@corp.com",
            body_text="Please review the attached Q4 financial summary before Monday's board meeting."
        )

        gemini_responses = iter([
            # Step 1: read emails
            ("", [{"name": "read_gmail_messages", "args": {"max_results": 3}}]),
            # Step 2: summarize one email
            ("", [{"name": "summarize_email", "args": {"email_id": 42}}]),
            # Final answer
            ("📊 *Q4 Report* from CFO requires your review before Monday's board meeting.", []),
        ])

        with (
            patch("app.agent.orchestrator.gemini_agent") as mock_gemini,
            patch("app.services.email_service.EmailService.ingest_gmail", new_callable=AsyncMock) as mock_ingest,
            patch("app.services.email_service.EmailService.summarize_email", new_callable=AsyncMock) as mock_summarize,
            patch("app.services.email_service.EmailService.get_email", new_callable=AsyncMock) as mock_get,
            patch("app.integrations.telegram.send_message", new_callable=AsyncMock) as mock_tg,
            patch("app.integrations.telegram.send_action_approval_prompt", new_callable=AsyncMock),
        ):
            mock_gemini.build_chat.return_value = MagicMock()
            mock_gemini.send_message.return_value = next(gemini_responses)
            mock_gemini.send_tool_result.side_effect = lambda *a, **kw: next(gemini_responses)

            mock_ingest.return_value = [fake_email]
            mock_get.return_value = fake_email
            mock_summarize.return_value = "Q4 financial summary requires review before Monday's board meeting."

            agent = Agent(db)
            await agent.handle_message(
                OWNER_CHAT_ID,
                "Read my emails and summarize the most important one",
                message_id=3,
            )

        # Both tools should have been called
        assert mock_ingest.called
        assert mock_summarize.called

        # Final message sent to user
        mock_tg.assert_called_once()
        final_text = mock_tg.call_args[0][1]
        assert "Q4" in final_text or "board" in final_text.lower()
