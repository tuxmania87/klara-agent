from __future__ import annotations
"""
Regelbasierte Kategorisierung von Transaktionen.
Regeln werden aus der DB geladen + built-in Defaults.
Nur bei confidence < threshold optional LLM-Fallback.
"""
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Kategorien ────────────────────────────────────────────────────────────────

CATEGORIES = [
    "Einkommen",
    "Wohnen/Miete",
    "Lebensmittel",
    "Drogerie/Beauty",
    "Klara/Styling",
    "Kinder/Familie",
    "Schule",
    "Gesundheit/Transition",
    "Mobilität",
    "Essen/Lieferdienste",
    "Abos/Software",
    "Technik/Projekte",
    "Content/Creator",
    "Reisen",
    "Versicherungen",
    "Steuern/Gebühren",
    "Barabhebung",
    "Rückerstattung",
    "Sparen/Transfers",
    "Sonstiges",
    "Unklar",
]

# ── Eingebaute Regeln (können durch DB-Regeln überschrieben werden) ───────────

@dataclass
class Rule:
    pattern: str
    category: str
    subcategory: str | None = None
    priority: int = 10
    field: str = "description"   # description | merchant


DEFAULT_RULES: list[Rule] = [
    # Einkommen
    Rule("gehalt",          "Einkommen", priority=20),
    Rule("lohn",            "Einkommen", priority=20),
    Rule("gutschrift",      "Einkommen", priority=5),
    Rule("erstattung finanzamt", "Einkommen", priority=20),
    # Wohnen
    Rule("miete",           "Wohnen/Miete", priority=20),
    Rule("nebenkosten",     "Wohnen/Miete", priority=15),
    Rule("hausverwaltung",  "Wohnen/Miete", priority=15),
    Rule("strom",           "Wohnen/Miete", "Energie", priority=15),
    Rule("gas ",            "Wohnen/Miete", "Energie", priority=15),
    Rule("stadtwerke",      "Wohnen/Miete", "Energie", priority=15),
    Rule("telekom",         "Abos/Software", "Internet/Telefon", priority=15),
    Rule("vodafone",        "Abos/Software", "Internet/Telefon", priority=15),
    Rule("o2 ",             "Abos/Software", "Internet/Telefon", priority=15),
    # Lebensmittel
    Rule("rewe",            "Lebensmittel", priority=20),
    Rule("edeka",           "Lebensmittel", priority=20),
    Rule("aldi",            "Lebensmittel", priority=20),
    Rule("lidl",            "Lebensmittel", priority=20),
    Rule("netto",           "Lebensmittel", priority=20),
    Rule("penny",           "Lebensmittel", priority=20),
    Rule("kaufland",        "Lebensmittel", priority=20),
    Rule("norma",           "Lebensmittel", priority=20),
    Rule("bäcker",          "Lebensmittel", priority=15),
    Rule("bakery",          "Lebensmittel", priority=10),
    # Drogerie
    Rule("dm ",             "Drogerie/Beauty", priority=20),
    Rule("dm-",             "Drogerie/Beauty", priority=20),
    Rule("rossmann",        "Drogerie/Beauty", priority=20),
    Rule("müller",          "Drogerie/Beauty", priority=15),
    # Klara/Styling
    Rule("bijou brigitte",  "Klara/Styling", priority=25),
    Rule("perücke",         "Klara/Styling", "Perücke", priority=25),
    Rule("hairshop",        "Klara/Styling", "Perücke", priority=20),
    Rule("hairdirect",      "Klara/Styling", "Perücke", priority=20),
    Rule("zara",            "Klara/Styling", priority=15),
    Rule("h&m",             "Klara/Styling", priority=15),
    Rule("about you",       "Klara/Styling", priority=15),
    Rule("zalando",         "Klara/Styling", priority=15),
    Rule("shein",           "Klara/Styling", priority=15),
    Rule("mac cosmetics",   "Klara/Styling", priority=20),
    Rule("sephora",         "Klara/Styling", priority=20),
    Rule("douglas",         "Klara/Styling", priority=20),
    # Kinder/Familie
    Rule("kindergarten",    "Kinder/Familie", priority=25),
    Rule("kita ",           "Kinder/Familie", priority=25),
    Rule("schulmaterial",   "Kinder/Familie", "Schule", priority=20),
    Rule("schulbuch",       "Kinder/Familie", "Schule", priority=20),
    Rule("spielzeug",       "Kinder/Familie", priority=15),
    Rule("smyths",          "Kinder/Familie", priority=15),
    # Gesundheit/Transition
    Rule("apotheke",        "Gesundheit/Transition", priority=20),
    Rule("arzt",            "Gesundheit/Transition", priority=20),
    Rule("krankenhaus",     "Gesundheit/Transition", priority=20),
    Rule("therapeut",       "Gesundheit/Transition", priority=20),
    Rule("krankenkasse",    "Gesundheit/Transition", priority=20),
    Rule("techniker krankenkasse", "Gesundheit/Transition", "TK", priority=25),
    Rule("barmer",          "Gesundheit/Transition", priority=20),
    Rule("aok",             "Gesundheit/Transition", priority=20),
    # Mobilität
    Rule("tankstelle",      "Mobilität", priority=15),
    Rule("aral",            "Mobilität", "Tanken", priority=20),
    Rule("shell",           "Mobilität", "Tanken", priority=15),
    Rule("bahn",            "Mobilität", "ÖPNV", priority=15),
    Rule("mvv",             "Mobilität", "ÖPNV", priority=20),
    Rule("vgn",             "Mobilität", "ÖPNV", priority=20),
    Rule("db ",             "Mobilität", "Bahn", priority=15),
    Rule("deutsche bahn",   "Mobilität", "Bahn", priority=20),
    Rule("flixbus",         "Mobilität", priority=15),
    Rule("uber",            "Mobilität", "Taxi", priority=15),
    Rule("parking",         "Mobilität", "Parken", priority=10),
    # Essen gehen
    Rule("lieferando",      "Essen/Lieferdienste", priority=20),
    Rule("uber eats",       "Essen/Lieferdienste", priority=20),
    Rule("mcdonald",        "Essen/Lieferdienste", priority=20),
    Rule("burger king",     "Essen/Lieferdienste", priority=20),
    Rule("pizza",           "Essen/Lieferdienste", priority=10),
    Rule("restaurant",      "Essen/Lieferdienste", priority=10),
    # Abos
    Rule("netflix",         "Abos/Software", "Netflix", priority=25),
    Rule("spotify",         "Abos/Software", "Spotify", priority=25),
    Rule("amazon prime",    "Abos/Software", "Amazon Prime", priority=25),
    Rule("disney",          "Abos/Software", "Disney+", priority=20),
    Rule("github",          "Abos/Software", "GitHub", priority=20),
    Rule("apple.com/bill",  "Abos/Software", "Apple", priority=20),
    Rule("google",          "Abos/Software", "Google", priority=10),
    Rule("microsoft",       "Abos/Software", "Microsoft", priority=15),
    Rule("chatgpt",         "Abos/Software", "OpenAI", priority=25),
    Rule("openai",          "Abos/Software", "OpenAI", priority=25),
    Rule("adobe",           "Abos/Software", "Adobe", priority=20),
    Rule("twitch",          "Content/Creator", priority=20),
    # Reisen
    Rule("alltours",        "Reisen", "Alltours", priority=25),
    Rule("airbnb",          "Reisen", priority=20),
    Rule("booking.com",     "Reisen", priority=20),
    Rule("hotel",           "Reisen", priority=10),
    Rule("flug",            "Reisen", priority=10),
    Rule("lufthansa",       "Reisen", priority=20),
    Rule("ryanair",         "Reisen", priority=20),
    Rule("eurowings",       "Reisen", priority=20),
    # Versicherungen
    Rule("versicherung",    "Versicherungen", priority=20),
    Rule("allianz",         "Versicherungen", priority=15),
    Rule("huk",             "Versicherungen", priority=15),
    Rule("ergo",            "Versicherungen", priority=15),
    # Steuern/Gebühren
    Rule("finanzamt",       "Steuern/Gebühren", priority=25),
    Rule("gebühr",          "Steuern/Gebühren", priority=10),
    Rule("kontoführung",    "Steuern/Gebühren", priority=20),
    # Barabhebung
    Rule("geldautomat",     "Barabhebung", priority=25),
    Rule("bargeldauszahlung", "Barabhebung", priority=25),
    Rule("cash withdrawal", "Barabhebung", priority=20),
    Rule("atm",             "Barabhebung", priority=15),
    # Rückerstattung — erkenne positive Buchungen mit Rückerstattungswörtern
    Rule("rückerstattung",  "Rückerstattung", priority=30),
    Rule("erstattung",      "Rückerstattung", priority=25),
    Rule("refund",          "Rückerstattung", priority=25),
    Rule("gutschrift",      "Rückerstattung", priority=5),   # niedrig, da auch Gehalt
    # Sparen/Transfers
    Rule("sparkasse",       "Sparen/Transfers", priority=10),
    Rule("tagesgeld",       "Sparen/Transfers", priority=20),
    Rule("umbuchung",       "Sparen/Transfers", priority=20),
    Rule("übertrag",        "Sparen/Transfers", priority=15),
]


def _match(text: str, pattern: str) -> bool:
    return pattern.lower() in text.lower()


def categorize(
    raw_description: str,
    raw_counterparty: str,
    amount: float,
    db_rules: list[dict] | None = None,
) -> tuple[str, str | None, float, str]:
    """
    Bestimmt Kategorie für eine Transaktion.
    Gibt (category, subcategory, confidence, source) zurück.
    source: 'rule_db' | 'rule_default' | 'amount_sign' | 'unclassified'
    """
    text = f"{raw_description} {raw_counterparty}".strip()

    # 1. Offensichtliche Rückerstattung: positiver Betrag mit Rückerstattungs-Keywords
    if amount > 0 and any(kw in text.lower() for kw in ["rückerstattung", "erstattung", "refund", "gutschrift"]):
        return "Rückerstattung", None, 0.95, "rule_default"

    # 2. DB-Regeln (User-definiert, höchste Priorität)
    if db_rules:
        best: tuple[int, Rule | None] = (-1, None)
        for r in db_rules:
            field_text = text if r.get("field", "description") == "description" else raw_counterparty
            if _match(field_text, r["pattern"]):
                if r.get("priority", 10) > best[0]:
                    best = (r["priority"], r)  # type: ignore
        if best[1]:
            r = best[1]
            return r["category"], r.get("subcategory"), 0.95, "rule_db"

    # 3. Eingebaute Default-Regeln
    best_default: tuple[int, Rule | None] = (-1, None)
    for rule in DEFAULT_RULES:
        field_text = text if rule.field == "description" else raw_counterparty
        if _match(field_text, rule.pattern):
            if rule.priority > best_default[0]:
                best_default = (rule.priority, rule)
    if best_default[1]:
        r = best_default[1]
        return r.category, r.subcategory, 0.85, "rule_default"

    # 4. Vorzeichen-Fallback
    if amount > 0:
        return "Einkommen", None, 0.3, "amount_sign"

    return "Unklar", None, 0.0, "unclassified"


def normalize_merchant(raw_counterparty: str, raw_description: str) -> str:
    """
    Erzeugt einen normalisierten Händlernamen aus den Rohdaten.
    Entfernt Nummern, Sonderzeichen, kürzt auf lesbare Länge.
    """
    text = (raw_counterparty or raw_description or "").strip()
    # Entferne typische Banknummern und Codes am Ende
    text = re.sub(r"\b\d{4,}\b", "", text)
    text = re.sub(r"[/\\|]{2,}", " ", text)
    # Mehrfache Leerzeichen
    text = re.sub(r"\s+", " ", text).strip()
    # Auf 60 Zeichen kürzen
    return text[:60] if text else "Unbekannt"
