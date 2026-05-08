"""
Email service — ingestion, deduplication, summarization, classification.
"""
import asyncio
import json
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime

import google.generativeai as genai
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.agent.prompts import load_prompt
from app.integrations.mailcow import mailcow_imap_client
from app.models.email import Email
from app.models.processed_email import ProcessedEmailId

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Ingestion ─────────────────────────────────────────────────────────────

    async def ingest_gmail(self, max_results: int = 20) -> list[Email]:
        """Fetch Gmail messages, deduplicate, store new ones."""
        from app.integrations.gmail import list_unread_messages

        raw_messages = await asyncio.get_event_loop().run_in_executor(
            None, lambda: list_unread_messages(max_results)
        )
        return await self._store_messages(raw_messages, source="gmail")

    async def ingest_mailcow(self, limit: int = 20) -> list[Email]:
        """Fetch Mailcow messages via IMAP, deduplicate, store new ones."""
        raw_messages = await mailcow_imap_client.list_unread_messages(limit=limit)
        # IMAP client already returns normalized dicts — pass through directly
        return await self._store_messages(raw_messages, source="mailcow")

    async def _store_messages(self, raw: list[dict], source: str) -> list[Email]:
        new_emails: list[Email] = []
        for m in raw:
            external_id = f"{source}:{m['id']}"

            # Check processed IDs
            existing = await self.db.execute(
                select(ProcessedEmailId).where(
                    ProcessedEmailId.external_id == external_id
                )
            )
            if existing.scalar_one_or_none():
                continue

            # Parse date
            received_at: datetime | None = None
            if m.get("date"):
                try:
                    received_at = parsedate_to_datetime(m["date"])
                except Exception:
                    pass

            email = Email(
                source=source,
                external_id=external_id,
                subject=m.get("subject"),
                sender=m.get("sender"),
                recipients=json.dumps(m.get("recipients", "")),
                body_text=m.get("body_text"),
                body_html=m.get("body_html"),
                received_at=received_at,
            )
            self.db.add(email)

            proc = ProcessedEmailId(source=source, external_id=external_id)
            self.db.add(proc)
            new_emails.append(email)

        await self.db.commit()
        logger.info("email_service.ingest", extra={"source": source, "new": len(new_emails)})
        return new_emails

    # ── Summarization ─────────────────────────────────────────────────────────

    async def summarize_email(self, email: Email) -> str:
        prompt_template = load_prompt("email_analysis_prompt.txt")
        prompt = prompt_template.format(
            subject=email.subject or "",
            sender=email.sender or "",
            body=(email.body_text or "")[:3000],
        )
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: model.generate_content(prompt)
        )
        summary = response.text.strip()

        email.summary = summary
        email.is_analyzed = True
        await self.db.commit()
        return summary

    # ── Classification ────────────────────────────────────────────────────────

    async def classify_actionability(self, email: Email) -> dict:
        prompt_template = load_prompt("email_analysis_prompt.txt")
        classify_prompt = (
            f"Analyze this email and return a JSON object with keys:\n"
            f"- is_actionable (bool)\n"
            f"- action_items (list of strings)\n"
            f"- suggested_calendar_events (list of objects with title, date_hint, duration_hint)\n\n"
            f"Email Subject: {email.subject}\n"
            f"From: {email.sender}\n"
            f"Body:\n{(email.body_text or '')[:3000]}\n\n"
            f"Return ONLY valid JSON."
        )
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: model.generate_content(classify_prompt)
        )
        raw = response.text.strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"is_actionable": False, "action_items": [], "suggested_calendar_events": []}

        email.is_actionable = result.get("is_actionable", False)
        email.actionable_items = json.dumps(result.get("action_items", []))
        email.is_analyzed = True
        await self.db.commit()
        return result

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_email(self, email_id: int) -> Email | None:
        result = await self.db.execute(select(Email).where(Email.id == email_id))
        return result.scalar_one_or_none()

    async def get_unanalyzed(self, limit: int = 10) -> list[Email]:
        result = await self.db.execute(
            select(Email).where(Email.is_analyzed == False).limit(limit)  # noqa
        )
        return list(result.scalars().all())
