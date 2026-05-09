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
from app.services.note_service import NoteService

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Dispatch Gemini tool calls to real integrations."""

    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.email_service = EmailService(db)
        self.action_service = ActionService(db)
        self.note_service = NoteService(db)

    @staticmethod
    def _sanitize_args(args: Any) -> Any:
        """Recursively convert protobuf/Gemini types to native Python types."""
        if hasattr(args, "items"):          # dict-like (MapComposite)
            return {k: ToolExecutor._sanitize_args(v) for k, v in args.items()}
        if hasattr(args, "__iter__") and not isinstance(args, (str, bytes)):
            return [ToolExecutor._sanitize_args(v) for v in args]
        return args

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Execute a tool call and return the result."""
        args = self._sanitize_args(args)
        logger.info("tool.execute", extra={"tool": tool_name, "args": args})

        dispatch = {
            "read_gmail_messages": self._read_gmail,
            "read_mailcow_messages": self._read_mailcow,
            "send_mailcow_email": self._queue_send_email,
            "create_google_calendar_event": self._queue_calendar_event,
            "list_google_calendar_events": self._list_calendar_events,
            "summarize_email": self._summarize_email,
            "classify_email_actionability": self._classify_emails,
            "get_agent_status": self._get_agent_status,
            "get_recent_emails": self._get_recent_emails,
            "update_google_calendar_event": self._queue_update_calendar_event,
            "delete_google_calendar_event": self._queue_delete_calendar_event,
            "find_google_calendar_events":  self._find_calendar_events,
            "save_note":    self._save_note,
            "list_notes":   self._list_notes,
            "search_notes": self._search_notes,
            "delete_note":  self._delete_note,
            "google_search": self._google_search,
        }

        handler = dispatch.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return await handler(**args)
        except Exception as e:
            logger.error(
                "tool.execute.error",
                extra={"tool": tool_name, "error": str(e)},
                exc_info=True,   # ← full traceback in logs
            )
            return {"error": str(e)}

    async def _read_gmail(self, max_results: int = 10) -> dict:
        max_results = int(max_results)
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
        limit = int(limit)
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
        from_addr: str | None = None,
    ) -> dict:
        """Create a pending action for email sending — requires approval."""
        payload = {
            "to": to,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "cc": cc or [],
            "from_addr": from_addr,
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
        desc = "Update Calendar Event\nEvent ID: " + event_id + "\nChanges: " + (changes or "none")
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
        max_results = int(max_results)
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


    async def _queue_update_calendar_event(
        self,
        event_id: str,
        title: str | None = None,
        start_iso: str | None = None,
        end_iso: str | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict:
        """Queue a calendar event update — requires approval."""
        payload = {
            "event_id": event_id,
            "title": title,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "description": description,
            "location": location,
        }
        changes = ", ".join(
            f"{k}={v}" for k, v in payload.items()
            if v is not None and k != "event_id"
        )
        desc = "Update Calendar Event\nEvent ID: " + event_id + "\nChanges: " + (changes or "none")
        action = await self.action_service.create_action(
            user_id=self.user_id,
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            payload=payload,
            description=desc,
        )
        return {"status": "pending_approval", "action_id": action.id,
                "message": "Calendar update queued for approval."}

    async def _queue_delete_calendar_event(
        self,
        event_id: str,
        title: str | None = None,
    ) -> dict:
        """Queue a calendar event deletion — requires approval."""
        payload = {"event_id": event_id, "action": "delete"}
        desc = "Delete Calendar Event\nTitle: " + (title or "Unknown") + "\nEvent ID: " + event_id
        action = await self.action_service.create_action(
            user_id=self.user_id,
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            payload=payload,
            description=desc,
        )
        return {"status": "pending_approval", "action_id": action.id,
                "message": "Calendar deletion queued for approval."}

    async def _find_calendar_events(self, query: str, max_results: int = 10) -> dict:
        """Search calendar events by text."""
        from app.integrations.google_calendar import find_events
        import asyncio
        max_results = int(max_results)
        events = await asyncio.get_event_loop().run_in_executor(
            None, lambda: find_events(query=query, max_results=max_results)
        )
        simplified = []
        for e in events:
            start = e.get("start", {})
            simplified.append({
                "id":       e.get("id"),
                "title":    e.get("summary"),
                "start":    start.get("dateTime") or start.get("date"),
                "location": e.get("location", ""),
            })
        return {"query": query, "count": len(simplified), "events": simplified}


    async def _queue_update_calendar_event(
        self,
        event_id: str,
        title: str | None = None,
        start_iso: str | None = None,
        end_iso: str | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict:
        payload = {
            "event_id": event_id, "title": title, "start_iso": start_iso,
            "end_iso": end_iso, "description": description, "location": location,
        }
        changes = ", ".join(f"{k}={v}" for k, v in payload.items() if v is not None and k != "event_id")
        desc = "Update Calendar Event / Event ID: " + event_id + " / Changes: " + (changes or "none")
        action = await self.action_service.create_action(
            user_id=self.user_id,
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            payload=payload,
            description=desc,
        )
        return {"status": "pending_approval", "action_id": action.id, "message": "Calendar update queued for approval."}

    async def _queue_delete_calendar_event(self, event_id: str, title: str | None = None) -> dict:
        payload = {"event_id": event_id, "action": "delete"}
        desc = "Delete Calendar Event / Title: " + (title or "Unknown") + " / Event ID: " + event_id
        action = await self.action_service.create_action(
            user_id=self.user_id,
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            payload=payload,
            description=desc,
        )
        return {"status": "pending_approval", "action_id": action.id, "message": "Calendar deletion queued for approval."}

    async def _find_calendar_events(self, query: str, max_results: int = 10) -> dict:
        from app.integrations.google_calendar import find_events
        import asyncio
        max_results = int(max_results)
        events = await asyncio.get_event_loop().run_in_executor(None, lambda: find_events(query=query, max_results=max_results))
        simplified = [{"id": e.get("id"), "title": e.get("summary"), "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"), "location": e.get("location", "")} for e in events]
        return {"query": query, "count": len(simplified), "events": simplified}


    async def _get_recent_emails(self, limit: int = 10, source: str | None = None) -> dict:
        """Query already-stored emails from DB — fast, no IMAP/Gmail call needed."""
        from sqlalchemy import select
        from app.models.email import Email
        limit = int(limit)

        stmt = select(Email).order_by(Email.received_at.desc()).limit(limit)
        if source:
            stmt = stmt.where(Email.source == source)

        result = await self.db.execute(stmt)
        emails = list(result.scalars().all())

        return {
            "count": len(emails),
            "emails": [
                {
                    "id":           e.id,
                    "source":       e.source,
                    "subject":      e.subject,
                    "sender":       e.sender,
                    "received_at":  str(e.received_at),
                    "snippet":      (e.body_text or "")[:300],
                    "summary":      e.summary,
                    "is_actionable": e.is_actionable,
                    "is_analyzed":  e.is_analyzed,
                }
                for e in emails
            ],
        }


    async def _get_agent_status(self) -> dict:
        """Return current agent configuration and stats."""
        from app.config import settings
        from sqlalchemy import select, func
        from app.models.email import Email
        from app.models.pending_action import PendingAction

        # Count emails in DB
        email_count_result = await self.db.execute(select(func.count()).select_from(Email))
        email_count = email_count_result.scalar() or 0

        pending_count_result = await self.db.execute(
            select(func.count()).select_from(PendingAction).where(
                PendingAction.status == "pending"
            )
        )
        pending_count = pending_count_result.scalar() or 0

        interval_min = settings.EMAIL_POLL_INTERVAL_SECONDS // 60

        return {
            "polling": {
                "enabled": True,
                "interval_minutes": interval_min,
                "description": f"Automatically polling every {interval_min} minutes in the background.",
            },
            "integrations": {
                "gmail":    "active" if settings.GMAIL_TOKEN_JSON else "not configured",
                "mailcow":  "active" if settings.MAILCOW_IMAP_HOST else "not configured",
                "calendar": "active" if settings.GCAL_TOKEN_JSON else "not configured",
                "telegram": "active",
            },
            "stats": {
                "emails_in_database": email_count,
                "pending_actions":    pending_count,
            },
            "workers": [
                f"email_poller — runs every {interval_min} min",
                f"email_analyzer — runs every {settings.ANALYSIS_POLL_INTERVAL_SECONDS} sec",
                f"notifier — runs every {settings.NOTIFICATION_POLL_INTERVAL_SECONDS} sec",
            ],
        }

    async def _classify_emails(self, email_ids: list[int]) -> dict:
        results = []
        for eid in email_ids:
            email = await self.email_service.get_email(eid)
            if email:
                result = await self.email_service.classify_actionability(email)
                results.append({"email_id": eid, **result})
        return {"results": results}

    # ── Notizen ───────────────────────────────────────────────────────────────

    async def _save_note(self, content: str, title: str | None = None, tags: str | None = None) -> dict:
        note = await self.note_service.create(
            user_id=self.user_id, content=content, title=title, tags=tags
        )
        return {
            "status": "saved",
            "note_id": note.id,
            "title": note.title,
            "tags": note.tags,
            "created_at": str(note.created_at),
        }

    async def _list_notes(self, limit: int = 10, tag: str | None = None) -> dict:
        notes = await self.note_service.list(user_id=self.user_id, limit=int(limit), tag=tag)
        return {
            "count": len(notes),
            "notes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "tags": n.tags,
                    "preview": n.content[:200],
                    "created_at": str(n.created_at),
                }
                for n in notes
            ],
        }

    async def _search_notes(self, query: str) -> dict:
        notes = await self.note_service.search(user_id=self.user_id, query=query)
        return {
            "query": query,
            "count": len(notes),
            "notes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "tags": n.tags,
                    "preview": n.content[:300],
                    "created_at": str(n.created_at),
                }
                for n in notes
            ],
        }

    async def _delete_note(self, note_id: int) -> dict:
        deleted = await self.note_service.delete(user_id=self.user_id, note_id=int(note_id))
        if deleted:
            return {"status": "deleted", "note_id": note_id}
        return {"status": "not_found", "note_id": note_id}

    # ── Google Search ─────────────────────────────────────────────────────────

    async def _google_search(self, query: str, num_results: int = 5) -> dict:
        from app.integrations.google_search import google_search
        results = await google_search(query=query, num_results=int(num_results))
        return {"query": query, "count": len(results), "results": results}
