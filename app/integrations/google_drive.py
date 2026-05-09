from __future__ import annotations
"""Google Drive Integration — CSV-Kontoauszüge aus einem konfigurierten Ordner lesen."""
import io
import logging
import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.config import settings

logger = logging.getLogger(__name__)


def _get_credentials() -> Credentials:
    creds = None
    token_path = settings.GDRIVE_TOKEN_JSON
    creds_path = settings.GDRIVE_CREDENTIALS_JSON

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, settings.GDRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, settings.GDRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def _build_service():
    return build("drive", "v3", credentials=_get_credentials(), cache_discovery=False)


def list_csv_files(folder_id: str) -> list[dict[str, str]]:
    """
    Listet alle CSV-Dateien im angegebenen Drive-Ordner.
    Gibt Liste von {id, name, modifiedTime} zurück.
    """
    service = _build_service()
    query = (
        f"'{folder_id}' in parents "
        f"and mimeType='text/csv' "
        f"and trashed=false"
    )
    result = service.files().list(
        q=query,
        fields="files(id, name, modifiedTime, size)",
        orderBy="modifiedTime desc",
    ).execute()

    files = result.get("files", [])
    logger.info("gdrive.list_csv", extra={"folder_id": folder_id, "count": len(files)})
    return files


def download_csv(file_id: str) -> bytes:
    """Lädt eine Datei aus Drive herunter und gibt den rohen Inhalt zurück."""
    service = _build_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    content = buffer.getvalue()
    logger.info("gdrive.download", extra={"file_id": file_id, "bytes": len(content)})
    return content
