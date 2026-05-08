"""
Telegram webhook endpoint.
"""
import base64
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.database import AsyncSessionLocal
from app.agent.orchestrator import Agent
from app.integrations.telegram import parse_update, download_file

router = APIRouter()
logger = logging.getLogger(__name__)

# Max file size we'll process (20 MB)
MAX_FILE_BYTES = 20 * 1024 * 1024


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook secret.")

    data = await request.json()
    logger.debug("telegram.webhook.received", extra={"update_id": data.get("update_id")})

    update = parse_update(data)
    chat_id = update.get("chat_id")

    if not chat_id:
        return {"ok": True}

    if chat_id != settings.TELEGRAM_OWNER_CHAT_ID:
        logger.warning("telegram.unauthorized", extra={"chat_id": chat_id})
        return {"ok": True}

    async with AsyncSessionLocal() as db:
        agent = Agent(db)

        if update.get("type") == "message":
            message_id = update.get("message_id", 0)
            text = update.get("text", "").strip()
            attachment = update.get("attachment")

            if attachment:
                await _handle_attachment(agent, chat_id, message_id, text, attachment)
            elif text:
                await agent.handle_message(chat_id, text, message_id)
            # else: empty message, ignore silently

        elif update.get("type") == "callback_query":
            await agent.handle_approval(
                chat_id,
                update.get("callback_data", ""),
                update.get("callback_query_id", ""),
            )

    return {"ok": True}


async def _handle_attachment(
    agent: Agent,
    chat_id: int,
    message_id: int,
    caption: str,
    attachment: dict,
) -> None:
    """Download attachment and pass it to the agent with context."""
    file_id = attachment["file_id"]
    file_name = attachment["file_name"]
    mime_type = attachment["mime_type"]
    file_size = attachment.get("file_size", 0)

    # Reject files that are too large
    if file_size > MAX_FILE_BYTES:
        from app.integrations.telegram import send_message
        await send_message(
            chat_id,
            f"File '{file_name}' is too large ({file_size // (1024*1024)} MB). Max 20 MB.",
        )
        return

    try:
        from app.integrations.telegram import send_message
        await send_message(chat_id, f"📎 Downloading {file_name}...")

        file_bytes = await download_file(file_id)

        # Build a context message for the agent
        if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
            content = _extract_pdf_text(file_bytes)
            user_message = (
                f"The user sent a PDF file: '{file_name}'\n"
                f"Caption: {caption or '(none)'}\n\n"
                f"PDF Content:\n{content}"
            )
        else:
            # For non-PDF documents, pass base64 and let Gemini handle it
            b64 = base64.b64encode(file_bytes).decode()
            user_message = (
                f"The user sent a file: '{file_name}' (type: {mime_type})\n"
                f"Caption: {caption or '(none)'}\n"
                f"[File content as base64: {b64[:500]}... truncated]"
            )

        await agent.handle_message(chat_id, user_message, message_id)

    except Exception as e:
        logger.error("telegram.attachment.error", extra={"file_id": file_id, "error": str(e)})
        from app.integrations.telegram import send_message
        await send_message(chat_id, f"Failed to process attachment '{file_name}': {e}")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes. Falls back gracefully if pypdf not available."""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {i+1}]\n{text}")
        full_text = "\n\n".join(pages)
        # Truncate to avoid hitting Gemini token limits
        if len(full_text) > 15000:
            full_text = full_text[:15000] + "\n\n[... truncated, document continues ...]"
        return full_text or "(No extractable text found in PDF)"
    except ImportError:
        return "(PDF text extraction not available — install pypdf)"
    except Exception as e:
        return f"(Could not extract PDF text: {e})"
