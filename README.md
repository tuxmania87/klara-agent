# 🤖 Personal AI Agent

A self-hosted, Dockerized personal assistant powered by **Gemini**, connected to **Gmail**, **Mailcow**, **Google Calendar**, and **Telegram**.

```
Telegram ──► Agent (Gemini) ──► Tools ──► Gmail / Mailcow / Google Calendar
                  │
                  └──► Approval Flow ──► Telegram inline buttons ──► Execute
```

---

## ✨ Features

| Capability | Details |
|---|---|
| 📬 Read Gmail | Polls inbox every 15 min, deduplicates, stores |
| 📮 Read Mailcow | Polls custom mail server via REST API |
| 🧠 AI Analysis | Summarizes emails, extracts action items via Gemini |
| 📅 Calendar | Creates Google Calendar events (with approval) |
| 📧 Send Email | Drafts and sends via Mailcow (with approval) |
| 💬 Telegram | Webhook-based chat interface with inline approval buttons |
| 🔒 Safety | ALL write operations require explicit user approval |

---

## 📁 Project Structure

```
project/
├── app/
│   ├── main.py                  # FastAPI app + lifespan
│   ├── config.py                # Pydantic settings (env-driven)
│   ├── database.py              # Async SQLAlchemy setup
│   ├── logging_config.py        # Structured JSON logging
│   ├── api/
│   │   └── routes/
│   │       ├── telegram.py      # Webhook endpoint
│   │       ├── health.py        # Health checks
│   │       └── actions.py       # Pending actions REST API
│   ├── agent/
│   │   ├── orchestrator.py      # Main reasoning loop
│   │   └── prompts.py           # Prompt file loader
│   ├── integrations/
│   │   ├── gmail.py             # Gmail API (read-only)
│   │   ├── mailcow.py           # Mailcow REST client
│   │   ├── telegram.py          # Telegram Bot API
│   │   ├── gemini.py            # Gemini + tool declarations
│   │   └── google_calendar.py   # Google Calendar API
│   ├── tools/
│   │   └── executor.py          # Tool dispatcher
│   ├── services/
│   │   ├── email_service.py     # Ingestion, summarization, classification
│   │   ├── action_service.py    # Pending action CRUD + execution
│   │   ├── user_service.py      # User management
│   │   └── message_service.py   # Conversation history
│   ├── models/                  # SQLAlchemy ORM models
│   └── workers/
│       ├── base.py              # Base polling worker
│       ├── email_poller.py      # Gmail + Mailcow polling (15 min)
│       ├── email_analyzer.py    # Auto-analyze new emails (60 sec)
│       └── notifier.py          # Telegram notifications (30 sec)
├── migrations/                  # Alembic async migrations
├── prompts/
│   ├── base_agent_prompt.txt    # System prompt
│   ├── email_analysis_prompt.txt
│   └── scheduling_prompt.txt
├── scripts/
│   ├── setup_gmail_auth.py      # One-time Gmail OAuth
│   ├── setup_gcal_auth.py       # One-time Calendar OAuth
│   └── set_telegram_webhook.py  # Register webhook URL
├── tests/
│   ├── unit/                    # Unit tests
│   └── integration/             # Integration tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 🚀 Quick Start

### Prerequisites

- Docker + Docker Compose
- A domain with HTTPS (for Telegram webhooks) — use [ngrok](https://ngrok.com/) for local dev
- Google Cloud project with **Gmail API** and **Google Calendar API** enabled
- Gemini API key from [Google AI Studio](https://aistudio.google.com/)
- Telegram bot token from [@BotFather](https://t.me/BotFather)

---

### Step 1 — Clone and configure

```bash
git clone <your-repo>
cd project
cp .env.example .env
# Edit .env with your credentials
nano .env
```

---

### Step 2 — Set up Google OAuth credentials

#### 2a. Create OAuth credentials in Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable **Gmail API** and **Google Calendar API**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Desktop app**
6. Download the JSON file

#### 2b. Generate tokens locally

```bash
# Create secrets directory
mkdir -p secrets

# Copy your downloaded credentials
cp ~/Downloads/client_secret_*.json secrets/gmail_credentials.json
cp secrets/gmail_credentials.json secrets/gcal_credentials.json  # Can reuse same file

# Install dependencies locally (just for auth scripts)
pip install google-auth-oauthlib google-generativeai pydantic-settings

# Authenticate Gmail (opens browser)
python scripts/setup_gmail_auth.py
# → saves secrets/gmail_token.json

# Authenticate Google Calendar (opens browser)
python scripts/setup_gcal_auth.py
# → saves secrets/gcal_token.json
```

Your `secrets/` directory should now contain:
```
secrets/
├── gmail_credentials.json
├── gmail_token.json
├── gcal_credentials.json
└── gcal_token.json
```

> ⚠️ **Never commit the `secrets/` directory!** It's in `.gitignore`.

---

### Step 3 — Create your Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token to `TELEGRAM_BOT_TOKEN` in `.env`
4. Message [@userinfobot](https://t.me/userinfobot) to get your chat ID
5. Set `TELEGRAM_OWNER_CHAT_ID` in `.env`

---

### Step 4 — Start the stack

```bash
docker compose up -d
```

This starts:
- **PostgreSQL** database
- **Alembic** migrations (runs once, then exits)
- **Agent** FastAPI app + background workers

Check logs:
```bash
docker compose logs -f agent
```

---

### Step 5 — Register the Telegram webhook

```bash
# For production (requires HTTPS domain)
python scripts/set_telegram_webhook.py https://yourdomain.com

# For local development with ngrok
ngrok http 8000
python scripts/set_telegram_webhook.py https://abc123.ngrok-free.app
```

---

### Step 6 — Start chatting!

Open Telegram, find your bot, and try:

```
Check my emails and summarize anything important
```

```
Are there any meetings I need to add to my calendar this week?
```

```
Draft a reply to the email from boss@company.com
```

---

## 💬 Usage Examples

### Reading and summarizing emails
```
You: Check my Gmail and summarize the last 5 emails

Agent: I found 3 unread emails:

1. **Invoice #4521** from billing@vendor.com
   → Payment due by Jan 20. Amount: €450.

2. **Team Standup** from hr@company.com
   → Daily standup moved to 10:30 tomorrow.

3. **Project Update** from client@startup.io
   → Requesting deliverable review by Friday.
```

### Approval flow for calendar events
```
You: Add the team standup to my calendar

Agent: ⏳ Pending Action #3

📅 Calendar Event
Title: Team Standup
Start: 2025-01-14T10:30:00+01:00
End: 2025-01-14T11:00:00+01:00

Do you approve this action?
[✅ Approve] [❌ Reject]

— You tap Approve —

Agent: ✅ Action #3 executed successfully.
Calendar event created: Team Standup on 2025-01-14T10:30:00+01:00
```

### Approval flow for sending email
```
You: Reply to the invoice email asking for a 2-week extension

Agent: ⏳ Pending Action #4

📧 Send Email
To: billing@vendor.com
Subject: Re: Invoice #4521 — Payment Extension Request
Body preview: Dear Team, I hope this message finds you well...

Do you approve this action?
[✅ Approve] [❌ Reject]
```

---

## 🔧 Configuration Reference

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `TELEGRAM_OWNER_CHAT_ID` | ✅ | Your personal Telegram chat ID |
| `TELEGRAM_WEBHOOK_SECRET` | ⬜ | Random string for webhook security |
| `GEMINI_API_KEY` | ✅ | Google AI Studio API key |
| `GEMINI_MODEL` | ⬜ | Default: `gemini-1.5-pro` |
| `GMAIL_CREDENTIALS_JSON` | ✅ | Path to OAuth credentials file |
| `GMAIL_TOKEN_JSON` | ✅ | Path to generated token file |
| `GCAL_CREDENTIALS_JSON` | ✅ | Path to Calendar OAuth credentials |
| `GCAL_TOKEN_JSON` | ✅ | Path to Calendar token file |
| `GCAL_TIMEZONE` | ⬜ | Default: `Europe/Berlin` |
| `MAILCOW_API_URL` | ⬜ | Your Mailcow instance URL |
| `MAILCOW_API_KEY` | ⬜ | Mailcow API key |
| `MAILCOW_EMAIL_ADDRESS` | ⬜ | Mailbox to read/send from |
| `DATABASE_URL` | ✅ | PostgreSQL async URL |
| `EMAIL_POLL_INTERVAL_SECONDS` | ⬜ | Default: 900 (15 min) |

---

## 🗄️ Database Models

| Table | Purpose |
|---|---|
| `users` | Telegram users (owner-only access) |
| `messages` | Conversation history per user |
| `emails` | Stored emails from Gmail + Mailcow |
| `calendar_events` | Created Google Calendar events |
| `pending_actions` | Write operations awaiting approval |
| `processed_email_ids` | Deduplication tracking |

---

## 🧪 Running Tests

```bash
# Install test dependencies
pip install -r requirements.txt
pip install aiosqlite  # for in-memory SQLite in tests

# Run all tests
pytest

# Run only unit tests
pytest tests/unit/

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=app --cov-report=html
```

---

## 🔒 Safety Architecture

The agent is designed with a **strict approval-first** policy:

1. **Read operations** (email reading, calendar listing) → executed immediately
2. **Write operations** (send email, create event) → always queued as `pending_action`
3. **Approval required** via Telegram inline keyboard buttons before execution
4. **Owner-only** — only messages from `TELEGRAM_OWNER_CHAT_ID` are processed
5. **Webhook secret** — optional but recommended to prevent webhook spoofing

The agent will **never** send an email or create a calendar event autonomously.

---

## 🏗️ Adding New Tools

1. Add a `FunctionDeclaration` to `app/integrations/gemini.py`
2. Add a handler method to `app/tools/executor.py`
3. Register the handler in `ToolExecutor.execute()`
4. Update `prompts/base_agent_prompt.txt` to describe the new capability

---

## 📊 Monitoring

```bash
# View structured logs
docker compose logs -f agent | python -m json.tool

# Check pending actions via REST API
curl http://localhost:8000/actions?status=pending

# Approve action via REST (alternative to Telegram)
curl -X POST http://localhost:8000/actions/1/approve

# Health check
curl http://localhost:8000/health
curl http://localhost:8000/health/db
```

---

## 🔄 Database Migrations

```bash
# Create a new migration after model changes
docker compose exec agent alembic revision --autogenerate -m "add new column"

# Apply migrations
docker compose exec agent alembic upgrade head

# Rollback one step
docker compose exec agent alembic downgrade -1
```

---

## 📝 License

MIT — use freely, self-host freely.
