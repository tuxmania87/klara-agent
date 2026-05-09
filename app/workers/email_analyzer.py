"""Email analysis worker — summarizes, classifies and triages new emails."""
from __future__ import annotations
import logging

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.email_service import EmailService
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class EmailAnalyzerWorker(BaseWorker):
    name = "email_analyzer"
    interval_seconds = settings.ANALYSIS_POLL_INTERVAL_SECONDS

    async def tick(self) -> None:
        async with AsyncSessionLocal() as db:
            service = EmailService(db)
            emails = await service.get_unanalyzed(limit=5)
            if not emails:
                return

            for email in emails:
                try:
                    await service.summarize_email(email)
                    result = await service.classify_actionability(email)
                    # Triage setzt triage_label — der Notifier filtert danach
                    triage = await service.triage_email(email)
                    logger.info(
                        "email_analyzer.analyzed",
                        extra={
                            "email_id": email.id,
                            "is_actionable": result.get("is_actionable"),
                            "triage_label": triage.get("triage_label"),
                        },
                    )
                except Exception as e:
                    logger.error(
                        "email_analyzer.error",
                        extra={"email_id": email.id, "error": str(e)},
                    )
