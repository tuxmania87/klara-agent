"""Integration tests for the Telegram webhook API endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock

from app.main import app
from app.config import settings


TELEGRAM_UPDATE_MESSAGE = {
    "update_id": 123456789,
    "message": {
        "message_id": 1,
        "from": {
            "id": settings.TELEGRAM_OWNER_CHAT_ID,
            "first_name": "Test",
            "last_name": "Owner",
            "username": "testowner",
        },
        "chat": {"id": settings.TELEGRAM_OWNER_CHAT_ID, "type": "private"},
        "text": "Check my emails",
        "date": 1700000000,
    },
}

TELEGRAM_UPDATE_CALLBACK = {
    "update_id": 123456790,
    "callback_query": {
        "id": "callback_001",
        "from": {
            "id": settings.TELEGRAM_OWNER_CHAT_ID,
            "first_name": "Test",
        },
        "message": {
            "message_id": 10,
            "chat": {"id": settings.TELEGRAM_OWNER_CHAT_ID},
        },
        "data": "approve_1",
    },
}


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


class TestTelegramWebhook:

    async def test_health_endpoint(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_webhook_rejects_unauthorized_chat(self, client):
        """Messages from non-owner chat IDs should be silently ignored."""
        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": 9999999, "first_name": "Stranger"},
                "chat": {"id": 9999999, "type": "private"},
                "text": "Hello",
                "date": 1700000000,
            },
        }
        with patch("app.agent.orchestrator.Agent.handle_message", new_callable=AsyncMock) as mock_agent:
            resp = await client.post("/webhook/telegram", json=update)

        assert resp.status_code == 200
        mock_agent.assert_not_called()

    async def test_webhook_dispatches_message_to_agent(self, client):
        with patch("app.agent.orchestrator.Agent.handle_message", new_callable=AsyncMock) as mock_agent:
            resp = await client.post("/webhook/telegram", json=TELEGRAM_UPDATE_MESSAGE)

        assert resp.status_code == 200
        mock_agent.assert_called_once()

    async def test_webhook_dispatches_callback_to_agent(self, client):
        with patch("app.agent.orchestrator.Agent.handle_approval", new_callable=AsyncMock) as mock_approval:
            resp = await client.post("/webhook/telegram", json=TELEGRAM_UPDATE_CALLBACK)

        assert resp.status_code == 200
        mock_approval.assert_called_once_with(
            settings.TELEGRAM_OWNER_CHAT_ID,
            "approve_1",
            "callback_001",
        )

    async def test_actions_list_endpoint(self, client):
        resp = await client.get("/actions?status=pending")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
