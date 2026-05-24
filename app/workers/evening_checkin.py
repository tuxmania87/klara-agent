from __future__ import annotations
"""
Abendlicher Check-in Worker — schreibt Klara täglich um 21 Uhr an.
Basiert auf ACT-Prinzipien: offen, wertschätzend, nicht klinisch.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.integrations import telegram as tg
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)

CHECKIN_HOUR   = 21
CHECKIN_MINUTE = 0

CHECKIN_MESSAGE = """Guten Abend 🌙

Wie war dein Tag? Ich bin da und höre zu — ob es etwas Schönes war, etwas Schwieriges, oder einfach ein ganz normaler Tag.

Du musst nichts Bestimmtes sagen. Einfach erzählen was gerade da ist."""


class EveningCheckinWorker(BaseWorker):
    name = "evening_checkin"
    interval_seconds = 60

    def __init__(self):
        super().__init__()
        self._sent_today: str | None = None  # "YYYY-MM-DD" des letzten Sendens

    async def tick(self) -> None:
        import pytz
        tz = pytz.timezone(settings.GCAL_TIMEZONE)
        now = datetime.now(tz)

        today_str = now.strftime("%Y-%m-%d")

        # Nur einmal pro Tag zur konfigurierten Uhrzeit
        if now.hour != CHECKIN_HOUR or now.minute != CHECKIN_MINUTE:
            return
        if self._sent_today == today_str:
            return

        try:
            await tg.send_message(settings.TELEGRAM_OWNER_CHAT_ID, CHECKIN_MESSAGE)
            self._sent_today = today_str
            logger.info("evening_checkin.sent", extra={"date": today_str})
        except Exception as e:
            logger.error("evening_checkin.error", extra={"error": str(e)})
