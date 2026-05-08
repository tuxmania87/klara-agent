"""
Gemini integration — reasoning engine with tool-calling support.
"""
import json
import logging
from typing import Any

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool

from app.config import settings
from app.agent.prompts import load_prompt

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.GEMINI_API_KEY)

# ── Tool declarations (schema Gemini understands) ─────────────────────────────

TOOL_DECLARATIONS = [
    FunctionDeclaration(
        name="read_gmail_messages",
        description="Read unread emails from Gmail inbox.",
        parameters={
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of emails to fetch. Default 10.",
                }
            },
        },
    ),
    FunctionDeclaration(
        name="read_mailcow_messages",
        description="Read unread emails from the Mailcow mailbox.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of emails to fetch. Default 20.",
                }
            },
        },
    ),
    FunctionDeclaration(
        name="send_mailcow_email",
        description=(
            "Queue an email to be sent via Mailcow. "
            "IMPORTANT: This creates a pending action that requires user approval before sending."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses.",
                },
                "subject": {"type": "string", "description": "Email subject."},
                "body_text": {"type": "string", "description": "Plain-text email body."},
                "body_html": {"type": "string", "description": "Optional HTML email body."},
                "cc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional CC recipients.",
                },
            },
            "required": ["to", "subject", "body_text"],
        },
    ),
    FunctionDeclaration(
        name="create_google_calendar_event",
        description=(
            "Queue a Google Calendar event for creation. "
            "IMPORTANT: This creates a pending action that requires user approval."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title."},
                "start_iso": {
                    "type": "string",
                    "description": "Start datetime in ISO 8601 format.",
                },
                "end_iso": {
                    "type": "string",
                    "description": "End datetime in ISO 8601 format.",
                },
                "description": {"type": "string", "description": "Event description."},
                "location": {"type": "string", "description": "Event location."},
            },
            "required": ["title", "start_iso", "end_iso"],
        },
    ),
    FunctionDeclaration(
        name="list_google_calendar_events",
        description="List upcoming events from Google Calendar.",
        parameters={
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum events to return. Default 10.",
                }
            },
        },
    ),
    FunctionDeclaration(
        name="summarize_email",
        description="Summarize a specific email by its database ID.",
        parameters={
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "integer",
                    "description": "Database ID of the email to summarize.",
                }
            },
            "required": ["email_id"],
        },
    ),
    FunctionDeclaration(
        name="classify_email_actionability",
        description="Classify which emails are actionable and extract action items.",
        parameters={
            "type": "object",
            "properties": {
                "email_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of email database IDs to classify.",
                }
            },
            "required": ["email_ids"],
        },
    ),
]

GEMINI_TOOLS = [Tool(function_declarations=TOOL_DECLARATIONS)]


class GeminiAgent:
    """Stateless Gemini reasoning agent. State is passed in each call."""

    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            tools=GEMINI_TOOLS,
            system_instruction=load_prompt("base_agent_prompt.txt"),
        )

    def build_chat(self, history: list[dict]) -> Any:
        """Create a chat session with conversation history."""
        gemini_history = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg["content"]]})
        return self.model.start_chat(history=gemini_history)

    def send_message(self, chat: Any, message: str) -> tuple[str, list[dict]]:
        """
        Send a message and return (text_response, tool_calls).
        tool_calls is a list of {"name": str, "args": dict}.
        """
        response = chat.send_message(message)
        tool_calls = []
        text_parts = []

        for part in response.parts:
            if fn := part.function_call:
                tool_calls.append({"name": fn.name, "args": dict(fn.args)})
                logger.info(
                    "gemini.tool_call",
                    extra={"tool": fn.name, "args": dict(fn.args)},
                )
            elif part.text:
                text_parts.append(part.text)

        return "\n".join(text_parts), tool_calls

    def send_tool_result(self, chat: Any, tool_name: str, result: Any) -> tuple[str, list[dict]]:
        """Send a tool result back to Gemini and get the next response."""
        response = chat.send_message(
            genai.protos.Part(
                function_response=genai.protos.FunctionResponse(
                    name=tool_name,
                    response={"result": json.dumps(result, default=str)},
                )
            )
        )
        tool_calls = []
        text_parts = []
        for part in response.parts:
            if fn := part.function_call:
                tool_calls.append({"name": fn.name, "args": dict(fn.args)})
            elif part.text:
                text_parts.append(part.text)
        return "\n".join(text_parts), tool_calls


gemini_agent = GeminiAgent()
