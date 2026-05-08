"""Unit tests for EmailService."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.email import Email
from app.services.email_service import EmailService


@pytest.fixture
def email_service(db):
    return EmailService(db)


SAMPLE_GMAIL_MESSAGES = [
    {
        "id": "msg_abc123",
        "subject": "Project Update — Q1 Review",
        "sender": "manager@company.com",
        "recipients": "you@company.com",
        "date": "Mon, 13 Jan 2025 09:30:00 +0100",
        "body_text": "Hi, please review the Q1 metrics by Friday.",
        "body_html": "<p>Hi, please review the Q1 metrics by Friday.</p>",
        "snippet": "Hi, please review the Q1 metrics by Friday.",
    }
]


class TestEmailService:

    async def test_ingest_gmail_stores_new_emails(self, email_service, mock_gmail):
        with patch(
            "app.integrations.gmail.list_unread_messages",
            return_value=SAMPLE_GMAIL_MESSAGES,
        ):
            emails = await email_service.ingest_gmail(max_results=10)

        assert len(emails) == 1
        assert emails[0].subject == "Project Update — Q1 Review"
        assert emails[0].source == "gmail"
        assert emails[0].sender == "manager@company.com"

    async def test_ingest_gmail_deduplicates(self, email_service, mock_gmail):
        with patch(
            "app.integrations.gmail.list_unread_messages",
            return_value=SAMPLE_GMAIL_MESSAGES,
        ):
            first = await email_service.ingest_gmail(max_results=10)
            second = await email_service.ingest_gmail(max_results=10)

        # Second ingestion should produce no new emails
        assert len(second) == 0

    async def test_get_email_returns_stored_email(self, email_service, db):
        email = Email(
            source="gmail",
            external_id="gmail:unique_test_id_999",
            subject="Hello",
            sender="a@b.com",
        )
        db.add(email)
        await db.commit()
        await db.refresh(email)

        result = await email_service.get_email(email.id)
        assert result is not None
        assert result.subject == "Hello"

    async def test_get_email_returns_none_for_missing(self, email_service):
        result = await email_service.get_email(999999)
        assert result is None

    async def test_get_unanalyzed_returns_unanalyzed_emails(self, email_service, db):
        for i in range(3):
            email = Email(
                source="mailcow",
                external_id=f"mailcow:unanalyzed_{i}",
                subject=f"Unanalyzed Email {i}",
                is_analyzed=False,
            )
            db.add(email)
        await db.commit()

        unanalyzed = await email_service.get_unanalyzed(limit=10)
        assert len(unanalyzed) >= 3

    async def test_summarize_email_calls_gemini(self, email_service, db):
        email = Email(
            source="gmail",
            external_id="gmail:summarize_test_001",
            subject="Budget Meeting Tomorrow",
            sender="boss@corp.com",
            body_text="We will discuss the 2025 budget tomorrow at 2pm in room 301.",
        )
        db.add(email)
        await db.commit()
        await db.refresh(email)

        mock_response = MagicMock()
        mock_response.text = "Budget meeting tomorrow at 2pm in room 301."

        with patch("google.generativeai.GenerativeModel") as MockModel:
            instance = MockModel.return_value
            instance.generate_content.return_value = mock_response

            summary = await email_service.summarize_email(email)

        assert summary == "Budget meeting tomorrow at 2pm in room 301."
        assert email.is_analyzed is True
