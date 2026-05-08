"""
Google Calendar integration — create and list events.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

logger = logging.getLogger(__name__)


def _get_credentials() -> Credentials:
    creds = None
    token_path = settings.GCAL_TOKEN_JSON
    creds_path = settings.GCAL_CREDENTIALS_JSON

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, settings.GCAL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, settings.GCAL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def _build_service():
    return build("calendar", "v3", credentials=_get_credentials(), cache_discovery=False)


def create_event(
    title: str,
    start: datetime,
    end: datetime,
    description: str = "",
    location: str = "",
    timezone: str | None = None,
) -> dict[str, Any]:
    """Create a Google Calendar event. Returns the created event resource."""
    tz = timezone or settings.GCAL_TIMEZONE
    try:
        service = _build_service()
        event_body = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
        }
        created = service.events().insert(calendarId="primary", body=event_body).execute()
        logger.info(
            "gcal.create_event",
            extra={"event_id": created["id"], "title": title},
        )
        return created
    except HttpError as e:
        logger.error("gcal.create_event.error", extra={"error": str(e)})
        raise


def list_events(
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """List upcoming events from the primary calendar."""
    try:
        service = _build_service()
        now = datetime.now(timezone.utc).isoformat()
        params: dict[str, Any] = {
            "calendarId": "primary",
            "timeMin": time_min.isoformat() if time_min else now,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max:
            params["timeMax"] = time_max.isoformat()

        result = service.events().list(**params).execute()
        events = result.get("items", [])
        logger.info("gcal.list_events", extra={"count": len(events)})
        return events
    except HttpError as e:
        logger.error("gcal.list_events.error", extra={"error": str(e)})
        raise
