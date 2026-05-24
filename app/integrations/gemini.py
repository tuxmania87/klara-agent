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
        parameters={"type": "object", "properties": {
            "max_results": {"type": "integer", "description": "Max emails to fetch. Default 10."},
        }},
    ),
    FunctionDeclaration(
        name="read_mailcow_messages",
        description="Read unread emails from the Mailcow mailbox via IMAP.",
        parameters={"type": "object", "properties": {
            "limit": {"type": "integer", "description": "Max emails to fetch. Default 20."},
        }},
    ),
    FunctionDeclaration(
        name="search_mailcow_messages",
        description="Sucht direkt per IMAP-SEARCH auf dem Mailserver — findet auch ältere Mails die nicht in der lokalen DB sind. Nutze dieses Tool wenn get_recent_emails nichts findet.",
        parameters={"type": "object", "properties": {
            "sender":       {"type": "string", "description": "Absender oder Domain, z.B. 'cantor-gymnasium.de' oder 'verena'."},
            "subject":      {"type": "string", "description": "Betreff-Stichwort, z.B. 'Rechnung' oder 'Turnier'."},
            "body_keyword": {"type": "string", "description": "Stichwort im Mailtext."},
            "limit":        {"type": "integer", "description": "Max. Anzahl Ergebnisse, default 10."},
        }},
    ),
    FunctionDeclaration(
        name="get_recent_emails",
        description="Sucht in der lokalen Mail-Datenbank. Nutze dieses Tool wenn der User nach Mails fragt — nach Absender, Betreff, Zeitraum oder einfach die letzten N. Schneller als IMAP/Gmail neu abzufragen.",
        parameters={"type": "object", "properties": {
            "limit":   {"type": "integer", "description": "Anzahl Mails, default 10."},
            "source":  {"type": "string",  "description": "Optional: gmail oder mailcow."},
            "sender":  {"type": "string",  "description": "Optional: Absender-Filter, z.B. 'amazon' oder 'verena@'. Sucht per ILIKE."},
            "subject": {"type": "string",  "description": "Optional: Betreff-Filter, z.B. 'Turnier' oder 'Rechnung'."},
        }},
    ),
    FunctionDeclaration(
        name="send_mailcow_email",
        description="Queue an email to be sent via SMTP. IMPORTANT: requires user approval before sending.",
        parameters={
            "type": "object",
            "properties": {
                "to":        {"type": "array", "items": {"type": "string"}, "description": "Recipient addresses."},
                "subject":   {"type": "string", "description": "Subject line."},
                "body_text": {"type": "string", "description": "Plain-text body."},
                "body_html": {"type": "string", "description": "Optional HTML body."},
                "cc":        {"type": "array", "items": {"type": "string"}, "description": "Optional CC."},
                "from_addr": {"type": "string", "description": "Absenderadresse. MUSS gesetzt werden wenn der User eine bestimmte Absenderadresse nennt, z.B. 'mail@klarahartmann.de' oder 'Klara Hartmann <mail@klarahartmann.de>'. Nie weglassen wenn explizit genannt."},
            },
            "required": ["to", "subject", "body_text"],
        },
    ),
    FunctionDeclaration(
        name="create_google_calendar_event",
        description="Queue a Google Calendar event for creation. Requires user approval.",
        parameters={
            "type": "object",
            "properties": {
                "title":       {"type": "string"},
                "start_iso":   {"type": "string", "description": "Start datetime ISO 8601."},
                "end_iso":     {"type": "string", "description": "End datetime ISO 8601."},
                "description": {"type": "string"},
                "location":    {"type": "string"},
            },
            "required": ["title", "start_iso", "end_iso"],
        },
    ),
    FunctionDeclaration(
        name="update_google_calendar_event",
        description="Queue an update to an existing Google Calendar event. Requires user approval. Use find_google_calendar_events first to get the event ID.",
        parameters={
            "type": "object",
            "properties": {
                "event_id":    {"type": "string", "description": "Google Calendar event ID."},
                "title":       {"type": "string", "description": "New title."},
                "start_iso":   {"type": "string", "description": "New start ISO 8601."},
                "end_iso":     {"type": "string", "description": "New end ISO 8601."},
                "description": {"type": "string", "description": "New description."},
                "location":    {"type": "string", "description": "New location."},
            },
            "required": ["event_id"],
        },
    ),
    FunctionDeclaration(
        name="delete_google_calendar_event",
        description="Queue deletion of a Google Calendar event. Requires user approval.",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID to delete."},
                "title":    {"type": "string", "description": "Event title for confirmation display."},
            },
            "required": ["event_id"],
        },
    ),
    FunctionDeclaration(
        name="find_google_calendar_events",
        description="Search Google Calendar events by keyword. Use this to find event IDs before updating or deleting.",
        parameters={
            "type": "object",
            "properties": {
                "query":       {"type": "string", "description": "Search text."},
                "max_results": {"type": "integer", "description": "Max results, default 10."},
            },
            "required": ["query"],
        },
    ),
    FunctionDeclaration(
        name="list_google_calendar_events",
        description="List upcoming events from Google Calendar.",
        parameters={"type": "object", "properties": {
            "max_results": {"type": "integer", "description": "Max events to return. Default 10."},
        }},
    ),
    FunctionDeclaration(
        name="summarize_email",
        description="Summarize a specific email by its database ID.",
        parameters={"type": "object", "properties": {
            "email_id": {"type": "integer", "description": "Database ID of the email."},
        }, "required": ["email_id"]},
    ),
    FunctionDeclaration(
        name="classify_email_actionability",
        description="Classify which emails are actionable and extract action items.",
        parameters={"type": "object", "properties": {
            "email_ids": {"type": "array", "items": {"type": "integer"}, "description": "List of email DB IDs."},
        }, "required": ["email_ids"]},
    ),
    FunctionDeclaration(
        name="get_current_time",
        description="Gibt die aktuelle Uhrzeit und das aktuelle Datum in der konfigurierten Zeitzone zurück. IMMER aufrufen wenn der User nach Datum, Uhrzeit, 'heute', 'jetzt', 'morgen' fragt oder wenn zeitbezogene Aktionen geplant werden.",
        parameters={"type": "object", "properties": {}},
    ),
    FunctionDeclaration(
        name="get_agent_status",
        description="Get current agent status: polling schedule, active integrations, email/action counts.",
        parameters={"type": "object", "properties": {}},
    ),
    FunctionDeclaration(
        name="save_note",
        description="Speichert eine Notiz für den User in der Datenbank.",
        parameters={
            "type": "object",
            "properties": {
                "content":  {"type": "string", "description": "Inhalt der Notiz."},
                "title":    {"type": "string", "description": "Optionaler Titel."},
                "tags":     {"type": "string", "description": "Optionale Tags, komma-separiert z.B. 'arbeit,idee'."},
                "category": {"type": "string", "description": "Kategorie: task|idea|shopping|kids|case|tech|routine|template|tagebuch"},
            },
            "required": ["content"],
        },
    ),
    FunctionDeclaration(
        name="list_diary",
        description="Zeigt Tagebucheinträge aus vergangenen Check-ins. Nutzen wenn der User fragt 'wie war meine Woche', 'was hab ich letzte Woche erzählt', 'zeig mein Tagebuch'.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Anzahl Einträge, default 7."},
            },
        },
    ),
    FunctionDeclaration(
        name="list_notes",
        description="Listet gespeicherte Notizen des Users auf.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximale Anzahl, default 10."},
                "tag":   {"type": "string",  "description": "Optional: nur Notizen mit diesem Tag."},
            },
        },
    ),
    FunctionDeclaration(
        name="search_notes",
        description="Durchsucht gespeicherte Notizen nach einem Stichwort.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Suchbegriff."},
            },
            "required": ["query"],
        },
    ),
    FunctionDeclaration(
        name="delete_note",
        description="Löscht eine Notiz anhand ihrer ID.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "ID der Notiz."},
            },
            "required": ["note_id"],
        },
    ),
    FunctionDeclaration(
        name="google_search",
        description="Führt eine Google-Suche durch und gibt die Top-Ergebnisse zurück.",
        parameters={
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "Suchanfrage."},
                "num_results": {"type": "integer", "description": "Anzahl Ergebnisse, default 5."},
            },
            "required": ["query"],
        },
    ),
    # ── Triage & Analyse ─────────────────────────────────────────────────────
    FunctionDeclaration(
        name="triage_email",
        description="Analysiert eine Mail tiefgehend: Triage-Label, To-dos, Dringlichkeit, beteiligte Personen, nächster Schritt.",
        parameters={
            "type": "object",
            "properties": {
                "email_id": {"type": "integer", "description": "DB-ID der E-Mail."},
            },
            "required": ["email_id"],
        },
    ),
    FunctionDeclaration(
        name="triage_inbox",
        description="Triagiert mehrere Mails auf einmal und gibt eine strukturierte Übersicht zurück. Ideal für morgendliches Briefing.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Anzahl der zu analysierenden Mails, default 10."},
            },
        },
    ),
    FunctionDeclaration(
        name="draft_reply",
        description="Erstellt einen Antwortentwurf für eine Mail in der passenden Tonlage. Sendet NICHT — nur Entwurf.",
        parameters={
            "type": "object",
            "properties": {
                "email_id": {"type": "integer"},
                "tone": {"type": "string", "description": "work|authority|school|private|social"},
            },
            "required": ["email_id"],
        },
    ),
    # ── Reminders ────────────────────────────────────────────────────────────
    FunctionDeclaration(
        name="set_reminder",
        description="Setzt eine Erinnerung zu einem bestimmten Zeitpunkt. Sybille schickt dann eine Telegram-Nachricht.",
        parameters={
            "type": "object",
            "properties": {
                "text":            {"type": "string", "description": "Text der Erinnerung."},
                "remind_at_iso":   {"type": "string", "description": "Zeitpunkt als ISO-8601, z.B. 2026-05-12T09:00:00."},
                "source_email_id": {"type": "integer", "description": "Optional: Bezug zu einer Mail."},
            },
            "required": ["text", "remind_at_iso"],
        },
    ),
    FunctionDeclaration(
        name="list_reminders",
        description="Zeigt alle offenen, noch nicht gesendeten Erinnerungen.",
        parameters={"type": "object", "properties": {}},
    ),
    FunctionDeclaration(
        name="delete_reminder",
        description="Löscht eine Erinnerung.",
        parameters={
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer"},
            },
            "required": ["reminder_id"],
        },
    ),
    # ── Cases / Chronologien ─────────────────────────────────────────────────
    FunctionDeclaration(
        name="create_case",
        description="Erstellt einen neuen Fall (z.B. 'Alltours-Reklamation', 'Schulproblem Klasse 3'). Dient als Chronologie.",
        parameters={
            "type": "object",
            "properties": {
                "title":       {"type": "string"},
                "description": {"type": "string", "description": "Kurze Beschreibung worum es geht."},
            },
            "required": ["title"],
        },
    ),
    FunctionDeclaration(
        name="list_cases",
        description="Listet alle laufenden oder abgeschlossenen Fälle.",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "open|resolved|waiting — leer = alle."},
            },
        },
    ),
    FunctionDeclaration(
        name="get_case",
        description="Zeigt einen Fall mit vollständiger Chronologie (alle Ereignisse in Zeitreihenfolge).",
        parameters={
            "type": "object",
            "properties": {
                "case_id": {"type": "integer"},
            },
            "required": ["case_id"],
        },
    ),
    FunctionDeclaration(
        name="add_case_event",
        description="Fügt einem Fall ein neues Ereignis hinzu (was ist passiert, wer war beteiligt, offene Fragen).",
        parameters={
            "type": "object",
            "properties": {
                "case_id":        {"type": "integer"},
                "description":    {"type": "string", "description": "Was ist passiert?"},
                "happened_at_iso":{"type": "string", "description": "Zeitpunkt ISO-8601, leer = jetzt."},
                "source":         {"type": "string", "description": "email|telegram|manual"},
                "involved":       {"type": "string", "description": "Beteiligte Personen/Organisationen."},
                "open_questions": {"type": "string", "description": "Noch offene Fragen."},
            },
            "required": ["case_id", "description"],
        },
    ),
    FunctionDeclaration(
        name="update_case_status",
        description="Aktualisiert Status und nächsten Schritt eines Falls.",
        parameters={
            "type": "object",
            "properties": {
                "case_id":   {"type": "integer"},
                "status":    {"type": "string", "description": "open|resolved|waiting"},
                "next_step": {"type": "string", "description": "Konkreter nächster Schritt."},
            },
            "required": ["case_id", "status"],
        },
    ),
    # ── Briefing ─────────────────────────────────────────────────────────────
    FunctionDeclaration(
        name="daily_briefing",
        description="Erstellt ein Tagesbriefing: Kalender heute, wichtige Mails, offene To-dos, fällige Reminders, Top-3-Prioritäten.",
        parameters={
            "type": "object",
            "properties": {
                "energy_level": {"type": "integer", "description": "Energielevel 1-10, beeinflusst die Planung. Optional."},
            },
        },
    ),
    FunctionDeclaration(
        name="evening_review",
        description="Abendreview: Was ist offen? Was sollte morgen zuerst? Was kann warten?",
        parameters={"type": "object", "properties": {}},
    ),
    # ── Finanzen ──────────────────────────────────────────────────────────────
    FunctionDeclaration(
        name="finance_list_drive_files",
        description="Listet CSV-Kontoauszüge im konfigurierten Google-Drive-Ordner. Zeigt welche schon importiert sind.",
        parameters={"type": "object", "properties": {}},
    ),
    FunctionDeclaration(
        name="finance_import_new",
        description="Importiert alle neuen CSV-Kontoauszüge aus Google Drive die noch nicht importiert wurden.",
        parameters={
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Kontoname, z.B. 'DKB Girokonto'. Optional."},
            },
        },
    ),
    FunctionDeclaration(
        name="finance_import_file",
        description="Importiert eine bestimmte CSV-Datei aus Google Drive anhand ihrer Drive-File-ID.",
        parameters={
            "type": "object",
            "properties": {
                "drive_file_id": {"type": "string", "description": "Google Drive File-ID."},
                "account_name": {"type": "string", "description": "Kontoname. Optional."},
                "dry_run": {"type": "boolean", "description": "Nur prüfen, nicht speichern."},
            },
            "required": ["drive_file_id"],
        },
    ),
    FunctionDeclaration(
        name="finance_monthly_report",
        description="Erstellt einen Finanzreport für einen bestimmten Monat: Einnahmen, Ausgaben, Kategorien, größte Buchungen.",
        parameters={
            "type": "object",
            "properties": {
                "year":  {"type": "integer", "description": "Jahr, z.B. 2026."},
                "month": {"type": "integer", "description": "Monat 1-12."},
            },
            "required": ["year", "month"],
        },
    ),
    FunctionDeclaration(
        name="finance_compare_months",
        description="Vergleicht zwei Monate Kategorie für Kategorie — zeigt Unterschiede und Abweichungen.",
        parameters={
            "type": "object",
            "properties": {
                "year1": {"type": "integer"}, "month1": {"type": "integer"},
                "year2": {"type": "integer"}, "month2": {"type": "integer"},
            },
            "required": ["year1", "month1", "year2", "month2"],
        },
    ),
    FunctionDeclaration(
        name="finance_subscriptions",
        description="Erkennt wiederkehrende Zahlungen/Abos und schätzt die monatlichen Gesamtkosten.",
        parameters={"type": "object", "properties": {}},
    ),
    FunctionDeclaration(
        name="finance_unclear",
        description="Zeigt Transaktionen mit unklarer Kategorisierung.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Anzahl, default 20."},
            },
        },
    ),
    FunctionDeclaration(
        name="finance_add_rule",
        description="Fügt eine Kategorisierungsregel hinzu und wendet sie sofort auf bestehende Transaktionen an. Z.B. 'REWE' → Lebensmittel.",
        parameters={
            "type": "object",
            "properties": {
                "pattern":    {"type": "string", "description": "Suchbegriff, z.B. 'REWE' oder 'Bijou Brigitte'."},
                "category":   {"type": "string", "description": "Zielkategorie."},
                "subcategory":{"type": "string", "description": "Unterkategorie. Optional."},
            },
            "required": ["pattern", "category"],
        },
    ),
    FunctionDeclaration(
        name="finance_recategorize",
        description="Korrigiert die Kategorie einer einzelnen Transaktion manuell.",
        parameters={
            "type": "object",
            "properties": {
                "transaction_id": {"type": "integer"},
                "category":       {"type": "string"},
                "subcategory":    {"type": "string", "description": "Optional."},
            },
            "required": ["transaction_id", "category"],
        },
    ),
    FunctionDeclaration(
        name="finance_set_budget",
        description="Setzt ein Monatsbudget für eine Kategorie.",
        parameters={
            "type": "object",
            "properties": {
                "category":   {"type": "string"},
                "amount":     {"type": "number", "description": "Budgetbetrag in Euro."},
                "month_year": {"type": "string", "description": "z.B. '2026-05' oder 'default' für dauerhaft."},
            },
            "required": ["category", "amount"],
        },
    ),
    FunctionDeclaration(
        name="finance_budget_status",
        description="Zeigt den aktuellen Budgetstatus für alle Kategorien im angegebenen Monat.",
        parameters={
            "type": "object",
            "properties": {
                "year":  {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
        },
    ),
    FunctionDeclaration(
        name="finance_refunds",
        description="Analysiert Rückerstattungen der letzten Monate — zeigt offene und gebuchte Erstattungen.",
        parameters={
            "type": "object",
            "properties": {
                "months_back": {"type": "integer", "description": "Wie viele Monate zurück, default 3."},
            },
        },
    ),
    FunctionDeclaration(
        name="finance_outliers",
        description="Findet ungewöhnliche Buchungen im Monat: sehr hohe Beträge, neue Händler, unklare Kategorien.",
        parameters={
            "type": "object",
            "properties": {
                "year":  {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
        },
    ),
    FunctionDeclaration(
        name="finance_list_imported",
        description="Zeigt alle bereits importierten Kontoauszugsdateien.",
        parameters={"type": "object", "properties": {}},
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
                    extra={"tool": fn.name, "tool_args": dict(fn.args)},
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
