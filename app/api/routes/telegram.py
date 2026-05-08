"""
Telegram webhook endpoint.
"""
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.database import AsyncSessionLocal
from app.agent.orchestrator import Agent
from app.integrations.telegram import parse_update

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    # Verify webhook secret if configured
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook secret.")

    data = await request.json()
    logger.debug("telegram.webhook.received", extra={"update": data})

    update = parse_update(data)
    chat_id = update.get("chat_id")

    if not chat_id:
        return {"ok": True}

    # Security: only allow the owner to use the agent
    if chat_id != settings.TELEGRAM_OWNER_CHAT_ID:
        logger.warning("telegram.unauthorized", extra={"chat_id": chat_id})
        return {"ok": True}

    async with AsyncSessionLocal() as db:
        agent = Agent(db)

        if update["type"] == "message":
            text = update.get("text", "").strip()
            message_id = update.get("message_id", 0)
            if text:
                await agent.handle_message(chat_id, text, message_id)

        elif update["type"] == "callback_query":
            callback_data = update.get("callback_data", "")
            callback_query_id = update.get("callback_query_id", "")
            await agent.handle_approval(chat_id, callback_data, callback_query_id)

    return {"ok": True}
