"""
Agent orchestrator — drives the Gemini reasoning + tool-calling loop.
"""
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.gemini import gemini_agent
from app.tools.executor import ToolExecutor
from app.services.user_service import UserService
from app.services.message_service import MessageService
from app.services.action_service import ActionService
from app.integrations import telegram as tg

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6   # prevent infinite loops


class Agent:
    """
    Processes a user message through the full Gemini reasoning loop.
    Handles tool calls, queues pending actions, and replies via Telegram.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_service = UserService(db)
        self.message_service = MessageService(db)
        self.action_service = ActionService(db)

    async def handle_message(self, chat_id: int, text: str, message_id: int) -> None:
        """Process a user message end-to-end."""
        # Ensure user exists
        user = await self.user_service.get_or_create(chat_id)

        # Persist user message
        await self.message_service.add(
            user_id=user.id,
            telegram_message_id=message_id,
            role="user",
            content=text,
        )

        # Load recent conversation history (last 20 messages)
        history = await self.message_service.get_history(user.id, limit=20)

        executor = ToolExecutor(db=self.db, user_id=user.id)

        # Start Gemini chat with history (exclude the last message — we send it fresh)
        chat = gemini_agent.build_chat(history[:-1])
        response_text, tool_calls = gemini_agent.send_message(chat, text)

        # Agentic loop
        rounds = 0
        while tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            for tc in tool_calls:
                result = await executor.execute(tc["name"], tc["args"])
                logger.info(
                    "agent.tool_result",
                    extra={"tool": tc["name"], "result_keys": list(result.keys()) if isinstance(result, dict) else "raw"},
                )
                response_text, tool_calls = gemini_agent.send_tool_result(chat, tc["name"], result)

        # Gemini gibt manchmal leeren Text zurück wenn es das Tool-Ergebnis
        # verarbeitet hat aber vergessen hat eine Antwort zu formulieren.
        # Dann explizit nachfragen.
        if not response_text and not tool_calls:
            response_text, _ = gemini_agent.send_message(
                chat,
                "Bitte formuliere jetzt eine klare Antwort auf Basis des Tool-Ergebnisses. "
                "Kein weiteres Tool nötig."
            )

        # Persist assistant reply
        await self.message_service.add(
            user_id=user.id,
            telegram_message_id=0,
            role="assistant",
            content=response_text,
        )

        # Send reply via Telegram (split if too long)
        for chunk in _split_message(response_text):
            await tg.send_message(chat_id, chunk)

        # Send approval prompts for any new pending actions
        pending = await self.action_service.get_pending_for_user(user.id)
        for action in pending:
            if action.telegram_message_id is None:
                msg = await tg.send_action_approval_prompt(
                    chat_id=chat_id,
                    action_id=action.id,
                    description=action.description,
                )
                await self.action_service.mark_notified(
                    action.id, msg["result"]["message_id"]
                )

    async def handle_approval(self, chat_id: int, callback_data: str, callback_query_id: str) -> None:
        """Handle approve/reject callback from Telegram inline keyboard."""
        user = await self.user_service.get_or_create(chat_id)

        parts = callback_data.split("_", 1)
        if len(parts) != 2:
            return
        decision, action_id_str = parts
        action_id = int(action_id_str)

        if decision == "approve":
            result_msg = await self.action_service.approve_and_execute(action_id)
            await tg.answer_callback_query(callback_query_id, "✅ Approved!")
            await tg.send_message(chat_id, result_msg)
        elif decision == "reject":
            await self.action_service.reject(action_id)
            await tg.answer_callback_query(callback_query_id, "❌ Rejected.")
            await tg.send_message(chat_id, f"Action #{action_id} has been rejected.")


def _split_message(text: str, limit: int = 4096) -> list[str]:
    """Split long messages into Telegram-compatible chunks."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
