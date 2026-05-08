"""Email polling worker — ingests Gmail and Mailcow on a schedule."""
import logging

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.email_service import EmailService
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class EmailPollerWorker(BaseWorker):
    name = "email_poller"
    interval_seconds = settings.EMAIL_POLL_INTERVAL_SECONDS

    async def tick(self) -> None:
        async with AsyncSessionLocal() as db:
            service = EmailService(db)

            # Poll Gmail
            try:
                gmail_new = await service.ingest_gmail()
                logger.info("email_poller.gmail", extra={"new_count": len(gmail_new)})
            except Exception as e:
                logger.error("email_poller.gmail.error", extra={"error": str(e)})

            # Poll Mailcow
            if settings.MAILCOW_API_URL:
                try:
                    mco_new = await service.ingest_mailcow()
                    logger.info("email_poller.mailcow", extra={"new_count": len(mco_new)})
                except Exception as e:
                    logger.error("email_poller.mailcow.error", extra={"error": str(e)})
