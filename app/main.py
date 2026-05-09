"""
Personal AI Agent - Main Application Entry Point
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import setup_logging
from app.api.routes import telegram, health, actions, emails

setup_logging()
from app.workers.email_poller import EmailPollerWorker
from app.workers.email_analyzer import EmailAnalyzerWorker
from app.workers.notifier import NotifierWorker
from app.database import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    logger.info("Starting Personal AI Agent...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized.")

    # Start background workers
    workers = [
        EmailPollerWorker(),
        EmailAnalyzerWorker(),
        NotifierWorker(),
    ]
    tasks = [asyncio.create_task(w.run()) for w in workers]
    logger.info(f"Started {len(tasks)} background workers.")

    yield

    # Shutdown
    logger.info("Shutting down workers...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Agent shut down cleanly.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Personal AI Agent",
        description="Self-hosted AI assistant with Gmail, Mailcow, Google Calendar, and Telegram integration.",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/health", tags=["Health"])
    app.include_router(telegram.router, prefix="/webhook", tags=["Telegram"])
    app.include_router(actions.router, prefix="/actions", tags=["Actions"])
    app.include_router(emails.router, prefix="/emails", tags=["Emails"])

    return app


app = create_app()
