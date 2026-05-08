"""Integration tests for Gmail client (mocked — no real API calls)."""
import pytest
from unittest.mock import MagicMock, patch


class TestGmailIntegration:

    def test_list_unread_messages_returns_expected_shape(self):
        """Verify message parsing produces the correct dict structure."""
        fake_message = {
            "id": "abc123",
            "threadId": "thread_xyz",
            "snippet": "Quick test email",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test Subject"},
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "To", "value": "bob@example.com"},
                    {"name": "Date", "value": "Mon, 13 Jan 2025 10:00:00 +0100"},
                ],
                "mimeType": "text/plain",
                "body": {
                    "data": "SGVsbG8sIHdvcmxkIQ=="  # "Hello, world!" in base64
                },
                "parts": [],
            },
        }

        mock_service = MagicMock()
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "abc123"}]
        }
        mock_service.users().messages().get().execute.return_value = fake_message

        with patch("app.integrations.gmail._build_service", return_value=mock_service):
            from app.integrations.gmail import list_unread_messages
            messages = list_unread_messages(max_results=5)

        assert len(messages) == 1
        msg = messages[0]
        assert msg["id"] == "abc123"
        assert msg["subject"] == "Test Subject"
        assert msg["sender"] == "alice@example.com"
        assert "Hello, world!" in msg["body_text"]

    def test_mark_as_read_calls_modify(self):
        mock_service = MagicMock()
        with patch("app.integrations.gmail._build_service", return_value=mock_service):
            from app.integrations.gmail import mark_as_read
            mark_as_read("abc123")

        mock_service.users().messages().modify.assert_called_once_with(
            userId="me",
            id="abc123",
            body={"removeLabelIds": ["UNREAD"]},
        )
