"""Integration tests for Mailcow API client (mocked)."""
import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from app.integrations.mailcow import MailcowClient


@pytest.fixture
def client():
    return MailcowClient()


class TestMailcowClient:

    async def test_list_messages_returns_messages(self, client):
        fake_response = [
            {"uid": "1", "subject": "Invoice #123", "from": "billing@vendor.com", "date": "2025-01-13"},
            {"uid": "2", "subject": "Meeting Invite", "from": "hr@company.com", "date": "2025-01-14"},
        ]

        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            messages = await client.list_messages(limit=10)

        assert len(messages) == 2
        assert messages[0]["subject"] == "Invoice #123"

    async def test_send_email_posts_correct_payload(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "sent"}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            post_mock = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__.return_value.post = post_mock

            result = await client.send_email(
                to=["recipient@example.com"],
                subject="Test Subject",
                body_text="Hello from agent.",
            )

        assert result["status"] == "sent"
        call_kwargs = post_mock.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["to"] == ["recipient@example.com"]
        assert payload["subject"] == "Test Subject"
