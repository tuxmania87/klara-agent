"""
Shared pytest fixtures.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base


# ── In-memory SQLite database for tests ──────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


# ── Common mocks ──────────────────────────────────────────────────────────────

@pytest.fixture
def mock_telegram_send():
    with patch("app.integrations.telegram.send_message", new_callable=AsyncMock) as m:
        m.return_value = {"ok": True, "result": {"message_id": 42}}
        yield m


@pytest.fixture
def mock_gemini():
    with patch("app.integrations.gemini.gemini_agent") as m:
        m.build_chat.return_value = MagicMock()
        m.send_message.return_value = ("I'll check your emails now.", [])
        yield m


@pytest.fixture
def mock_gmail():
    with patch("app.integrations.gmail.list_unread_messages") as m:
        m.return_value = [
            {
                "id": "gmail_001",
                "subject": "Test Email",
                "sender": "sender@example.com",
                "recipients": "you@example.com",
                "date": "Mon, 01 Jan 2024 10:00:00 +0100",
                "body_text": "Hello, this is a test email body.",
                "body_html": "<p>Hello, this is a test email body.</p>",
                "snippet": "Hello, this is a test email body.",
            }
        ]
        yield m
