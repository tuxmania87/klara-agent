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
from app.services.reminder_service import ReminderService
from app.services.case_service import CaseService
from app.services.finance_service import FinanceService

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Dispatch Gemini tool calls to real integrations."""

    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id
        self.email_service = EmailService(db)
        self.action_service = ActionService(db)
        self.note_service = NoteService(db)
        self.reminder_service = ReminderService(db)
        self.case_service = CaseService(db)
        self.finance_service = FinanceService(db)

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
        logger.info("tool.execute", extra={"tool": tool_name, "tool_args": args})

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
            # Triage & Analyse
            "triage_email":  self._triage_email,
            "triage_inbox":  self._triage_inbox,
            "draft_reply":   self._draft_reply,
            # Reminders
            "set_reminder":    self._set_reminder,
            "list_reminders":  self._list_reminders,
            "delete_reminder": self._delete_reminder,
            # Cases
            "create_case":       self._create_case,
            "list_cases":        self._list_cases,
            "get_case":          self._get_case,
            "add_case_event":    self._add_case_event,
            "update_case_status":self._update_case_status,
            # Briefing
            "daily_briefing":  self._daily_briefing,
            "evening_review":  self._evening_review,
            # Finanzen
            "finance_list_drive_files": self._finance_list_drive_files,
            "finance_import_new":       self._finance_import_new,
            "finance_import_file":      self._finance_import_file,
            "finance_monthly_report":   self._finance_monthly_report,
            "finance_compare_months":   self._finance_compare_months,
            "finance_subscriptions":    self._finance_subscriptions,
            "finance_unclear":          self._finance_unclear,
            "finance_add_rule":         self._finance_add_rule,
            "finance_recategorize":     self._finance_recategorize,
            "finance_set_budget":       self._finance_set_budget,
            "finance_budget_status":    self._finance_budget_status,
            "finance_refunds":          self._finance_refunds,
            "finance_outliers":         self._finance_outliers,
            "finance_list_imported":    self._finance_list_imported,
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
        desc = f"Neuer Kalendertermin: {title}\n{start_iso} → {end_iso}"
        if description:
            desc += f"\n{description}"
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

    # ── Triage & Analyse ──────────────────────────────────────────────────────

    async def _triage_email(self, email_id: int) -> dict:
        email = await self.email_service.get_email(int(email_id))
        if not email:
            return {"error": f"E-Mail {email_id} nicht gefunden."}
        result = await self.email_service.triage_email(email)
        result["email_id"] = email_id
        result["subject"] = email.subject
        result["sender"] = email.sender
        return result

    async def _triage_inbox(self, limit: int = 10) -> dict:
        from sqlalchemy import select
        from app.models.email import Email
        limit = int(limit)
        result = await self.db.execute(
            select(Email).order_by(Email.received_at.desc()).limit(limit)
        )
        emails = list(result.scalars().all())
        summaries = []
        label_counts: dict[str, int] = {}
        for email in emails:
            triage = await self.email_service.triage_email(email)
            label = triage.get("triage_label", "info")
            label_counts[label] = label_counts.get(label, 0) + 1
            summaries.append({
                "email_id":     email.id,
                "subject":      email.subject,
                "sender":       email.sender,
                "triage_label": label,
                "triage_reason":triage.get("triage_reason"),
                "what_to_do":   triage.get("what_to_do"),
                "by_when":      triage.get("by_when"),
                "how_critical": triage.get("how_critical"),
                "next_step":    triage.get("next_step"),
            })
        return {
            "total": len(summaries),
            "label_summary": label_counts,
            "emails": summaries,
        }

    async def _draft_reply(self, email_id: int, tone: str | None = None) -> dict:
        email = await self.email_service.get_email(int(email_id))
        if not email:
            return {"error": f"E-Mail {email_id} nicht gefunden."}
        draft = await self.email_service.draft_reply(email, tone=tone)
        return {
            "email_id": email_id,
            "subject":  email.subject,
            "tone":     tone or email.tone or "work",
            "draft":    draft,
            "note":     "Entwurf gespeichert. Zum Senden: send_mailcow_email mit diesem Text verwenden — erfordert Bestätigung.",
        }

    # ── Reminders ─────────────────────────────────────────────────────────────

    async def _set_reminder(self, text: str, remind_at_iso: str, source_email_id: int | None = None) -> dict:
        from datetime import datetime, timezone
        try:
            remind_at = datetime.fromisoformat(remind_at_iso)
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return {"error": f"Ungültiges Datum: {remind_at_iso}"}
        reminder = await self.reminder_service.create(
            user_id=self.user_id,
            text=text,
            remind_at=remind_at,
            source_email_id=int(source_email_id) if source_email_id else None,
        )
        return {
            "status": "created",
            "reminder_id": reminder.id,
            "text": text,
            "remind_at": str(remind_at),
        }

    async def _list_reminders(self) -> dict:
        reminders = await self.reminder_service.get_upcoming(self.user_id, limit=20)
        return {
            "count": len(reminders),
            "reminders": [
                {
                    "id": r.id,
                    "text": r.text,
                    "remind_at": str(r.remind_at),
                    "source_email_id": r.source_email_id,
                }
                for r in reminders
            ],
        }

    async def _delete_reminder(self, reminder_id: int) -> dict:
        deleted = await self.reminder_service.delete(self.user_id, int(reminder_id))
        return {"status": "deleted" if deleted else "not_found", "reminder_id": reminder_id}

    # ── Cases ─────────────────────────────────────────────────────────────────

    async def _create_case(self, title: str, description: str | None = None) -> dict:
        case = await self.case_service.create(self.user_id, title=title, description=description)
        return {"status": "created", "case_id": case.id, "title": case.title}

    async def _list_cases(self, status: str | None = None) -> dict:
        cases = await self.case_service.list(self.user_id, status=status or None)
        return {
            "count": len(cases),
            "cases": [
                {
                    "id": c.id,
                    "title": c.title,
                    "status": c.status,
                    "next_step": c.next_step,
                    "updated_at": str(c.updated_at),
                }
                for c in cases
            ],
        }

    async def _get_case(self, case_id: int) -> dict:
        case = await self.case_service.get_with_events(self.user_id, int(case_id))
        if not case:
            return {"error": f"Fall {case_id} nicht gefunden."}
        events = await self.case_service.get_events(int(case_id))
        return {
            "id": case.id,
            "title": case.title,
            "description": case.description,
            "status": case.status,
            "next_step": case.next_step,
            "events": [
                {
                    "id": e.id,
                    "happened_at": str(e.happened_at),
                    "description": e.description,
                    "source": e.source,
                    "involved": e.involved,
                    "open_questions": e.open_questions,
                }
                for e in events
            ],
        }

    async def _add_case_event(
        self,
        case_id: int,
        description: str,
        happened_at_iso: str | None = None,
        source: str | None = None,
        involved: str | None = None,
        open_questions: str | None = None,
    ) -> dict:
        from datetime import datetime, timezone
        happened_at = None
        if happened_at_iso:
            try:
                happened_at = datetime.fromisoformat(happened_at_iso)
                if happened_at.tzinfo is None:
                    happened_at = happened_at.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        event = await self.case_service.add_event(
            case_id=int(case_id),
            description=description,
            happened_at=happened_at,
            source=source,
            involved=involved,
            open_questions=open_questions,
        )
        return {"status": "added", "event_id": event.id, "case_id": case_id}

    async def _update_case_status(self, case_id: int, status: str, next_step: str | None = None) -> dict:
        case = await self.case_service.update_status(self.user_id, int(case_id), status, next_step)
        if not case:
            return {"error": f"Fall {case_id} nicht gefunden."}
        return {"status": "updated", "case_id": case_id, "new_status": status, "next_step": next_step}

    # ── Briefing ──────────────────────────────────────────────────────────────

    async def _daily_briefing(self, energy_level: int | None = None) -> dict:
        """Sammelt alle relevanten Daten für ein Tagesbriefing."""
        from sqlalchemy import select, func as sqlfunc
        from app.models.email import Email
        from app.models.note import Note
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # Kalender heute
        from app.integrations.google_calendar import list_events
        import asyncio
        try:
            events = await asyncio.get_event_loop().run_in_executor(None, lambda: list_events(max_results=10))
            today_events = [
                {"title": e.get("summary"), "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date")}
                for e in events
            ]
        except Exception:
            today_events = []

        # Ungelesene / nicht triagierte Mails
        mail_result = await self.db.execute(
            select(Email)
            .where(Email.triage_label.in_(["urgent", "needs_reply", "needs_appointment", "needs_followup"]))
            .order_by(Email.received_at.desc())
            .limit(10)
        )
        priority_mails = list(mail_result.scalars().all())

        # Offene Reminders
        reminders = await self.reminder_service.get_upcoming(self.user_id, limit=10)
        due_today = [r for r in reminders if r.remind_at.date() <= now.date()]

        # Offene Notizen mit Due-Date
        notes_result = await self.db.execute(
            select(Note)
            .where(Note.user_id == self.user_id)
            .where(Note.status == "open")
            .where(Note.due_date <= today_end)
            .order_by(Note.due_date)
            .limit(10)
        )
        due_notes = list(notes_result.scalars().all())

        # Offene Fälle
        open_cases = await self.case_service.list(self.user_id, status="open", limit=5)

        return {
            "date": now.strftime("%A, %d.%m.%Y"),
            "energy_level": energy_level,
            "calendar_today": today_events,
            "priority_mails": [
                {"id": m.id, "subject": m.subject, "sender": m.sender,
                 "triage_label": m.triage_label, "next_step": m.triage_reason}
                for m in priority_mails
            ],
            "reminders_due_today": [
                {"id": r.id, "text": r.text, "remind_at": str(r.remind_at)}
                for r in due_today
            ],
            "notes_due": [
                {"id": n.id, "title": n.title, "due_date": str(n.due_date)}
                for n in due_notes
            ],
            "open_cases": [
                {"id": c.id, "title": c.title, "next_step": c.next_step}
                for c in open_cases
            ],
        }

    async def _evening_review(self) -> dict:
        """Was ist heute offen geblieben? Was morgen?"""
        from sqlalchemy import select
        from app.models.email import Email
        from app.models.note import Note
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        tomorrow_end = (now + timedelta(days=1)).replace(hour=23, minute=59)

        # Mails die noch Aktion brauchen
        mail_result = await self.db.execute(
            select(Email)
            .where(Email.triage_label.in_(["urgent", "needs_reply", "needs_followup"]))
            .where(Email.is_read == False)  # noqa
            .order_by(Email.received_at.desc())
            .limit(10)
        )
        open_mails = list(mail_result.scalars().all())

        # Reminders bis morgen
        reminders = await self.reminder_service.get_upcoming(self.user_id, limit=10)
        tomorrow_reminders = [r for r in reminders if r.remind_at <= tomorrow_end]

        # Offene Notizen / To-dos
        notes_result = await self.db.execute(
            select(Note)
            .where(Note.user_id == self.user_id)
            .where(Note.status == "open")
            .where(Note.category == "task")
            .order_by(Note.due_date.asc().nulls_last())
            .limit(10)
        )
        open_tasks = list(notes_result.scalars().all())

        return {
            "open_mails_needing_action": [
                {"id": m.id, "subject": m.subject, "triage_label": m.triage_label}
                for m in open_mails
            ],
            "reminders_until_tomorrow": [
                {"id": r.id, "text": r.text, "remind_at": str(r.remind_at)}
                for r in tomorrow_reminders
            ],
            "open_tasks": [
                {"id": n.id, "title": n.title or n.content[:80], "due_date": str(n.due_date) if n.due_date else None}
                for n in open_tasks
            ],
        }

    # ── Finanzen ──────────────────────────────────────────────────────────────

    async def _finance_list_drive_files(self) -> dict:
        files = await self.finance_service.list_drive_files()
        new = [f for f in files if not f.get("already_imported") and "error" not in f]
        return {"total": len(files), "new_files": len(new), "files": files}

    async def _finance_import_new(self, account_name: str | None = None) -> dict:
        return await self.finance_service.import_new_files()

    async def _finance_import_file(self, drive_file_id: str, account_name: str | None = None, dry_run: bool = False) -> dict:
        return await self.finance_service.import_file(drive_file_id, account_name=account_name, dry_run=dry_run)

    async def _finance_monthly_report(self, year: int, month: int) -> dict:
        return await self.finance_service.monthly_report(int(year), int(month))

    async def _finance_compare_months(self, year1: int, month1: int, year2: int, month2: int) -> dict:
        return await self.finance_service.compare_months(int(year1), int(month1), int(year2), int(month2))

    async def _finance_subscriptions(self) -> dict:
        return await self.finance_service.detect_subscriptions()

    async def _finance_unclear(self, limit: int = 20) -> dict:
        txs = await self.finance_service.get_unclear_transactions(limit=int(limit))
        return {"count": len(txs), "transactions": txs}

    async def _finance_add_rule(self, pattern: str, category: str, subcategory: str | None = None) -> dict:
        return await self.finance_service.add_rule(pattern, category, subcategory=subcategory)

    async def _finance_recategorize(self, transaction_id: int, category: str, subcategory: str | None = None) -> dict:
        return await self.finance_service.recategorize(int(transaction_id), category, subcategory)

    async def _finance_set_budget(self, category: str, amount: float, month_year: str = "default") -> dict:
        return await self.finance_service.set_budget(category, float(amount), month_year)

    async def _finance_budget_status(self, year: int, month: int) -> dict:
        status = await self.finance_service.budget_status(int(year), int(month))
        return {"budget_status": status}

    async def _finance_refunds(self, months_back: int = 3) -> dict:
        return await self.finance_service.refund_analysis(months_back=int(months_back))

    async def _finance_outliers(self, year: int, month: int) -> dict:
        return await self.finance_service.outliers(int(year), int(month))

    async def _finance_list_imported(self) -> dict:
        files = await self.finance_service.list_imported_files()
        return {"count": len(files), "files": files}
