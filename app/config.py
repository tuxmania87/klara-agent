"""
Application configuration — loads from environment variables.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────────
    APP_ENV: str = "production"
    SECRET_KEY: str = "changeme"
    LOG_LEVEL: str = "INFO"

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://agent:agent@db:5432/agentdb"

    # ── Telegram ─────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_OWNER_CHAT_ID: int  # Your personal Telegram chat ID

    # ── Gemini ───────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-1.5-pro"

    # ── Gmail ────────────────────────────────────────────────────────────────
    GMAIL_CREDENTIALS_JSON: str = "/secrets/gmail_credentials.json"
    GMAIL_TOKEN_JSON: str = "/secrets/gmail_token.json"
    GMAIL_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    # ── Google Calendar ──────────────────────────────────────────────────────
    GCAL_CREDENTIALS_JSON: str = "/secrets/gcal_credentials.json"
    GCAL_TOKEN_JSON: str = "/secrets/gcal_token.json"
    GCAL_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/calendar",
    ]
    GCAL_TIMEZONE: str = "Europe/Berlin"

    # ── Mailcow ──────────────────────────────────────────────────────────────
    MAILCOW_API_URL: str = ""          # e.g. https://mail.example.com/api/v1
    MAILCOW_API_KEY: str = ""
    MAILCOW_EMAIL_ADDRESS: str = ""    # mailbox to read/send from
    MAILCOW_IMAP_HOST: str = ""        # e.g. mail.example.com
    MAILCOW_IMAP_PORT: int = 993
    MAILCOW_IMAP_PASSWORD: str = ""    # mailbox password (not API key)
    MAILCOW_IMAP_SSL: bool = True

    # ── Mailcow SMTP (for sending emails) ────────────────────────────────────
    MAILCOW_SMTP_HOST: str = ""        # usually same as IMAP host
    MAILCOW_SMTP_PORT: int = 587       # 587 = STARTTLS, 465 = implicit TLS
    MAILCOW_SMTP_PASSWORD: str = ""    # usually same as IMAP password
    MAILCOW_SMTP_TLS: bool = False     # False = STARTTLS (port 587), True = implicit TLS (port 465)

    # ── Worker settings ──────────────────────────────────────────────────────
    EMAIL_POLL_INTERVAL_SECONDS: int = 900    # 15 min
    ANALYSIS_POLL_INTERVAL_SECONDS: int = 60
    NOTIFICATION_POLL_INTERVAL_SECONDS: int = 30
    GMAIL_MAX_RESULTS: int = 20

    # ── Prompts ──────────────────────────────────────────────────────────────
    PROMPTS_DIR: str = "/app/prompts"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
