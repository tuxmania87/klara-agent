"""
Action service — manages pending actions and executes approved ones.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_action import ActionStatus, ActionType, PendingAction

logger = logging.getLogger(__name__)


class ActionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_action(
        self,
        user_id: int,
        action_type: ActionType,
        payload: dict,
        description: str,
        source_email_id: int | None = None,
    ) -> PendingAction:
        action = PendingAction(
            user_id=user_id,
            action_type=action_type,
            payload=json.dumps(payload),
            description=description,
            source_email_id=source_email_id,
        )
        self.db.add(action)
        await self.db.commit()
        await self.db.refresh(action)
        logger.info("action_service.create", extra={"action_id": action.id, "type": action_type})
        return action

    async def get_pending_for_user(self, user_id: int) -> list[PendingAction]:
        result = await self.db.execute(
            select(PendingAction).where(
                PendingAction.user_id == user_id,
                PendingAction.status == ActionStatus.PENDING,
                PendingAction.telegram_message_id.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_all_pending(self) -> list[PendingAction]:
        result = await self.db.execute(
            select(PendingAction).where(PendingAction.status == ActionStatus.PENDING)
        )
        return list(result.scalars().all())

    async def mark_notified(self, action_id: int, telegram_message_id: int) -> None:
        action = await self._get(action_id)
        if action:
            action.telegram_message_id = telegram_message_id
            await self.db.commit()

    async def approve_and_execute(self, action_id: int) -> str:
        action = await self._get(action_id)
        if not action:
            return f"Action #{action_id} not found."
        if action.status != ActionStatus.PENDING:
            return f"Action #{action_id} is already {action.status}."

        action.status = ActionStatus.APPROVED
        await self.db.commit()

        try:
            result = await self._execute(action)
            action.status = ActionStatus.EXECUTED
            action.resolved_at = datetime.now(timezone.utc)
            await self.db.commit()
            logger.info("action_service.executed", extra={"action_id": action_id})
            return f"✅ Action #{action_id} executed successfully.\n{result}"
        except Exception as e:
            action.status = ActionStatus.FAILED
            action.error_message = str(e)
            action.resolved_at = datetime.now(timezone.utc)
            await self.db.commit()
            logger.error("action_service.failed", extra={"action_id": action_id, "error": str(e)})
            return f"❌ Action #{action_id} failed: {e}"

    async def reject(self, action_id: int) -> None:
        action = await self._get(action_id)
        if action:
            action.status = ActionStatus.REJECTED
            action.resolved_at = datetime.now(timezone.utc)
            await self.db.commit()
            logger.info("action_service.rejected", extra={"action_id": action_id})

    async def _get(self, action_id: int) -> PendingAction | None:
        result = await self.db.execute(
            select(PendingAction).where(PendingAction.id == action_id)
        )
        return result.scalar_one_or_none()

    async def _execute(self, action: PendingAction) -> str:
        payload = json.loads(action.payload)

        if action.action_type == ActionType.SEND_EMAIL:
            from app.integrations.mailcow import mailcow_client
            await mailcow_client.send_email(
                to=payload["to"],
                subject=payload["subject"],
                body_text=payload["body_text"],
                body_html=payload.get("body_html"),
                cc=payload.get("cc"),
            )
            return f"Email sent to {', '.join(payload['to'])} — Subject: {payload['subject']}"

        elif action.action_type == ActionType.CREATE_CALENDAR_EVENT:
            from app.integrations.google_calendar import create_event
            from datetime import datetime

            start = datetime.fromisoformat(payload["start_iso"])
            end = datetime.fromisoformat(payload["end_iso"])
            event = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: create_event(
                    title=payload["title"],
                    start=start,
                    end=end,
                    description=payload.get("description", ""),
                    location=payload.get("location", ""),
                ),
            )
            return f"Calendar event created: {payload['title']} on {payload['start_iso']}"

        return "Executed."
