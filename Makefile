.PHONY: help up down logs build restart shell test test-unit test-integration \
        migrate migrate-new webhook-set lint format db-reset

# ── Config ────────────────────────────────────────────────────────────────────
COMPOSE     = docker compose
SERVICE     = agent
PYTHON      = python
PYTEST      = pytest

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Docker ────────────────────────────────────────────────────────────────────
up:  ## Start all services (detached)
	$(COMPOSE) up -d

down:  ## Stop all services
	$(COMPOSE) down

build:  ## Rebuild Docker images
	$(COMPOSE) build --no-cache

restart:  ## Restart the agent service only
	$(COMPOSE) restart $(SERVICE)

logs:  ## Tail agent logs
	$(COMPOSE) logs -f $(SERVICE)

logs-all:  ## Tail all service logs
	$(COMPOSE) logs -f

shell:  ## Open a bash shell inside the agent container
	$(COMPOSE) exec $(SERVICE) bash

# ── Database ──────────────────────────────────────────────────────────────────
migrate:  ## Run Alembic migrations (upgrade head)
	$(COMPOSE) exec $(SERVICE) alembic upgrade head

migrate-new:  ## Create a new migration (usage: make migrate-new MSG="add column")
	$(COMPOSE) exec $(SERVICE) alembic revision --autogenerate -m "$(MSG)"

migrate-down:  ## Roll back one migration step
	$(COMPOSE) exec $(SERVICE) alembic downgrade -1

migrate-history:  ## Show migration history
	$(COMPOSE) exec $(SERVICE) alembic history --verbose

db-reset:  ## ⚠️  Drop and recreate the database (loses all data!)
	$(COMPOSE) down -v
	$(COMPOSE) up -d db
	sleep 3
	$(COMPOSE) up migrate
	$(COMPOSE) up -d $(SERVICE)

# ── Tests ─────────────────────────────────────────────────────────────────────
test:  ## Run all tests
	$(PYTEST) -v

test-unit:  ## Run unit tests only
	$(PYTEST) tests/unit/ -v

test-integration:  ## Run integration tests only
	$(PYTEST) tests/integration/ -v

test-cov:  ## Run tests with HTML coverage report
	$(PYTEST) --cov=app --cov-report=html --cov-report=term-missing
	@echo "Coverage report: htmlcov/index.html"

# ── Auth setup ────────────────────────────────────────────────────────────────
auth-gmail:  ## Run the Gmail OAuth setup flow
	$(PYTHON) scripts/setup_gmail_auth.py

auth-gcal:  ## Run the Google Calendar OAuth setup flow
	$(PYTHON) scripts/setup_gcal_auth.py

auth-all:  auth-gmail auth-gcal  ## Run both OAuth setup flows

# ── Telegram ──────────────────────────────────────────────────────────────────
webhook-set:  ## Register Telegram webhook (usage: make webhook-set URL=https://yourdomain.com)
	$(PYTHON) scripts/set_telegram_webhook.py $(URL)

webhook-local:  ## Register webhook using ngrok (requires ngrok running on port 8000)
	@NGROK_URL=$$(curl -s http://localhost:4040/api/tunnels | python -c \
		"import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])"); \
	$(PYTHON) scripts/set_telegram_webhook.py $$NGROK_URL

# ── Code quality ──────────────────────────────────────────────────────────────
lint:  ## Run ruff linter
	ruff check app/ tests/

format:  ## Auto-format with ruff
	ruff format app/ tests/

typecheck:  ## Run mypy type checker
	mypy app/ --ignore-missing-imports

# ── Health checks ─────────────────────────────────────────────────────────────
health:  ## Check service health endpoint
	@curl -s http://localhost:8000/health | python -m json.tool

health-db:  ## Check database connection
	@curl -s http://localhost:8000/health/db | python -m json.tool

# ── Operations ────────────────────────────────────────────────────────────────
pending:  ## List pending actions
	@curl -s "http://localhost:8000/actions?status=pending" | python -m json.tool

approve:  ## Approve action by ID (usage: make approve ID=1)
	@curl -s -X POST http://localhost:8000/actions/$(ID)/approve | python -m json.tool

reject:  ## Reject action by ID (usage: make reject ID=1)
	@curl -s -X POST http://localhost:8000/actions/$(ID)/reject | python -m json.tool

ingest-gmail:  ## Manually trigger Gmail ingestion
	@curl -s -X POST http://localhost:8000/emails/ingest/gmail | python -m json.tool

ingest-mailcow:  ## Manually trigger Mailcow ingestion
	@curl -s -X POST http://localhost:8000/emails/ingest/mailcow | python -m json.tool
