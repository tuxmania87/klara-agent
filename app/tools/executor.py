"""
Tool executor — maps Gemini function-call names to Python implementations.
"""
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pending_action import ActionType, ActionStatus
from app.services.email_service import EmailService
from app.services.action_service import ActionService

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Dispatch Gemini tool calls to real integrations."""

    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.email_service = EmailService(db)
        self.action_service = ActionService(db)

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Execute a tool call and return the result."""
        logger.info("tool.execute", extra={"tool": tool_name, "args": args})

        dispatch = {
            "read_gmail_messages": self._read_gmail,
            "read_mailcow_messages": self._read_mailcow,
            "send_mailcow_email": self._queue_send_email,
            "create_google_calendar_event": self._queue_calendar_event,
            "list_google_calendar_events": self._list_calendar_events,
            "summarize_email": self._summarize_email,
            "classify_email_actionability": self._classify_emails,
        }

        handler = dispatch.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return await handler(**args)
        except Exception as e:
            logger.error("tool.execute.error", extra={"tool": tool_name, "error": str(e)})
            return {"error": str(e)}

    async def _read_gmail(self, max_results: int = 10) -> dict:
        messages = await self.email_service.ingest_gmail(max_results=max_results)
        return {
            "source": "gmail",
            "count": len(messages),
            "emails": [
                {
                    "id": m.id,
                    "subject": m.subject,
                    "sender": m.sender,
                    "snippet": (m.body_text or "")[:200],
                    "received_at": str(m.received_at),
                }
                for m in messages
            ],
        }

    async def _read_mailcow(self, limit: int = 20) -> dict:
        messages = await self.email_service.ingest_mailcow(limit=limit)
        return {
            "source": "mailcow",
            "count": len(messages),
            "emails": [
                {
                    "id": m.id,
                    "subject": m.subject,
                    "sender": m.sender,
                    "snippet": (m.body_text or "")[:200],
                    "received_at": str(m.received_at),
                }
                for m in messages
            ],
        }

    async def _queue_send_email(
        self,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
        cc: list[str] | None = None,
    ) -> dict:
        """Create a pending action for email sending — requires approval."""
        payload = {
            "to": to,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "cc": cc or [],
        }
        description = (
            f"📧 *Send Email*\n"
            f"To: {', '.join(to)}\n"
            f"Subject: {subject}\n"
            f"Body preview: {body_text[:150]}..."
        )
        action = await self.action_service.create_action(
            user_id=self.user_id,
            action_type=ActionType.SEND_EMAIL,
            payload=payload,
            description=description,
        )
        return {
            "status": "pending_approval",
            "action_id": action.id,
            "message": "Email queued for approval. User must confirm before sending.",
        }

    async def _queue_calendar_event(
        self,
        title: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        location: str = "",
    ) -> dict:
        """Create a pending action for calendar event creation — requires approval."""
        payload = {
            "title": title,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "description": description,
            "location": location,
        }
        desc = (
            f"📅 *Calendar Event*\n"
            f"Title: {title}\n"
            f"Start: {start_iso}\n"
            f"End: {end_iso}\n"
            f"Location: {location or 'N/A'}"
        )
        action = await self.action_service.create_action(
            user_id=self.user_id,
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            payload=payload,
            description=desc,
        )
        return {
            "status": "pending_approval",
            "action_id": action.id,
            "message": "Calendar event queued for approval. User must confirm before creating.",
        }

    async def _list_calendar_events(self, max_results: int = 10) -> dict:
        from app.integrations.google_calendar import list_events
        import asyncio

        events = await asyncio.get_event_loop().run_in_executor(
            None, lambda: list_events(max_results=max_results)
        )
        simplified = []
        for e in events:
            start = e.get("start", {})
            simplified.append(
                {
                    "id": e.get("id"),
                    "title": e.get("summary"),
                    "start": start.get("dateTime") or start.get("date"),
                    "location": e.get("location", ""),
                }
            )
        return {"count": len(simplified), "events": simplified}

    async def _summarize_email(self, email_id: int) -> dict:
        email = await self.email_service.get_email(email_id)
        if not email:
            return {"error": f"Email {email_id} not found."}
        summary = await self.email_service.summarize_email(email)
        return {"email_id": email_id, "summary": summary}

    async def _classify_emails(self, email_ids: list[int]) -> dict:
        results = []
        for eid in email_ids:
            email = await self.email_service.get_email(eid)
            if email:
                result = await self.email_service.classify_actionability(email)
                results.append({"email_id": eid, **result})
        return {"results": results}
