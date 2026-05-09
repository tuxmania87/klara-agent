from __future__ import annotations
"""
CSV-Parser für Kontoauszüge.
Unterstützt: DKB Girokonto, DKB Visa, generisches Format.
Gibt immer normalisierte Dicts zurück.
"""
import hashlib
import io
import logging
import re
from datetime import date
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Normalisiertes Ergebnis eines geparsten Datensatzes
NormalizedRow = dict[str, Any]


# ── Format-Erkennung ──────────────────────────────────────────────────────────

def detect_format(content: bytes) -> str:
    """
    Erkennt das CSV-Format anhand von Header-Schlüsselwörtern.
    Gibt zurück: 'dkb_giro' | 'dkb_visa' | 'generic'
    """
    try:
        sample = content[:2000].decode("utf-8", errors="replace").lower()
    except Exception:
        return "generic"

    # Visa-spezifisch: "umsatz abgerechnet" als Spaltenname
    if "umsatz abgerechnet" in sample:
        return "dkb_visa"
    # Giro: hat Buchungsdatum + Wertstellung + Auftraggeber — das sind Giro-typische Kombis
    if "buchungsdatum" in sample and "wertstellung" in sample and "auftraggeber" in sample:
        return "dkb_giro"
    # Giro alternativ: Belegdatum + Buchungstext (ältere Exporte)
    if "belegdatum" in sample and "buchungstext" in sample and "auftraggeber" in sample:
        return "dkb_giro"
    # Visa alternativ: Belegdatum ohne Auftraggeber
    if "belegdatum" in sample and "beschreibung" in sample:
        return "dkb_visa"
    return "generic"


# ── DKB Girokonto ─────────────────────────────────────────────────────────────

def _parse_dkb_giro(df: pd.DataFrame) -> list[NormalizedRow]:
    """
    DKB Girokonto CSV.
    Typische Spalten: Buchungsdatum, Wertstellung, Auftraggeber / Beguenstigter,
    Kontonummer, BLZ, Betrag (EUR), Buchungstext
    """
    # Normalisiere Spaltennamen für robustes Matching
    col_map = {c.strip().lower(): c for c in df.columns}

    def get(row, *keys):
        for k in keys:
            for col_lower, col_orig in col_map.items():
                if k.lower() in col_lower:
                    val = row.get(col_orig, "")
                    if str(val).strip() not in ("", "nan", "NaT"):
                        return str(val).strip()
        return ""

    rows = []
    for idx, r in df.iterrows():
        try:
            booking_date = _parse_date(get(r, "buchungsdatum"))
            if not booking_date:
                continue
            value_date = _parse_date(get(r, "wertstellung"))
            amount = _parse_amount(get(r, "betrag (eur)", "betrag"))
            # Auftraggeber / Begünstigter ist die wichtigste Counterparty-Info
            counterparty = get(r, "auftraggeber", "beguenstigter", "zahlungsempfänger", "empfänger")
            # Buchungstext + Verwendungszweck als Description
            description = get(r, "buchungstext", "verwendungszweck")
            rows.append({
                "booking_date": booking_date,
                "value_date": value_date,
                "amount": amount,
                "currency": "EUR",
                "raw_description": description,
                "raw_counterparty": counterparty,
                "_source_row": idx,
            })
        except Exception as e:
            logger.warning("csv_parser.dkb_giro.row_error", extra={"row": idx, "error": str(e)})
    return rows


# ── DKB Visa ──────────────────────────────────────────────────────────────────

def _parse_dkb_visa(df: pd.DataFrame) -> list[NormalizedRow]:
    """
    DKB Visa Kreditkartenabrechnung.
    Typische Spalten: Umsatz abgerechnet, Belegdatum, Beschreibung, Betrag (EUR)
    """
    rows = []
    for idx, r in df.iterrows():
        try:
            booking_date = _parse_date(
                r.get("Belegdatum") or r.get("Umsatz abgerechnet") or r.get("Buchungsdatum", "")
            )
            if not booking_date:
                continue
            amount = _parse_amount(
                r.get("Betrag (EUR)") or r.get("Betrag") or r.get("betrag (eur)", "0")
            )
            description = str(r.get("Beschreibung") or r.get("Buchungstext") or "").strip()
            counterparty = str(r.get("Gläubiger-ID") or r.get("Glaeubiger-ID") or "").strip()
            rows.append({
                "booking_date": booking_date,
                "value_date": None,
                "amount": amount,
                "currency": "EUR",
                "raw_description": description,
                "raw_counterparty": counterparty,
                "_source_row": idx,
            })
        except Exception as e:
            logger.warning("csv_parser.dkb_visa.row_error", extra={"row": idx, "error": str(e)})
    return rows


# ── Generisch ─────────────────────────────────────────────────────────────────

_GENERIC_DATE_COLS = ["datum", "date", "buchungsdatum", "buchungstag", "wertdatum", "belegdatum"]
_GENERIC_AMOUNT_COLS = ["betrag", "amount", "umsatz", "betrag (eur)", "wert"]
_GENERIC_DESC_COLS = ["beschreibung", "buchungstext", "verwendungszweck", "description", "text"]
_GENERIC_PARTY_COLS = ["auftraggeber", "empfänger", "counterparty", "merchant", "name"]


def _parse_generic(df: pd.DataFrame) -> list[NormalizedRow]:
    cols_lower = {c.lower(): c for c in df.columns}

    date_col = next((cols_lower[c] for c in _GENERIC_DATE_COLS if c in cols_lower), None)
    amount_col = next((cols_lower[c] for c in _GENERIC_AMOUNT_COLS if c in cols_lower), None)
    desc_col = next((cols_lower[c] for c in _GENERIC_DESC_COLS if c in cols_lower), None)
    party_col = next((cols_lower[c] for c in _GENERIC_PARTY_COLS if c in cols_lower), None)

    if not date_col or not amount_col:
        raise ValueError(
            f"Unbekanntes CSV-Format. Gefundene Spalten: {list(df.columns)[:10]}. "
            f"Benötigt werden mindestens eine Datum- und eine Betragsspalte."
        )

    rows = []
    for idx, r in df.iterrows():
        try:
            booking_date = _parse_date(str(r[date_col]))
            if not booking_date:
                continue
            amount = _parse_amount(str(r[amount_col]))
            description = str(r[desc_col]).strip() if desc_col else ""
            counterparty = str(r[party_col]).strip() if party_col else ""
            rows.append({
                "booking_date": booking_date,
                "value_date": None,
                "amount": amount,
                "currency": "EUR",
                "raw_description": description,
                "raw_counterparty": counterparty,
                "_source_row": idx,
            })
        except Exception as e:
            logger.warning("csv_parser.generic.row_error", extra={"row": idx, "error": str(e)})
    return rows


# ── Hilfsroutinen ─────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> date | None:
    if not raw or str(raw).strip() in ("", "nan", "NaT"):
        return None
    raw = str(raw).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%y"):
        try:
            return pd.to_datetime(raw, format=fmt).date()
        except Exception:
            pass
    try:
        return pd.to_datetime(raw, dayfirst=True).date()
    except Exception:
        return None


def _parse_amount(raw: str) -> float:
    if not raw or str(raw).strip() in ("", "nan"):
        return 0.0
    raw = str(raw).strip()
    # DKB nutzt Komma als Dezimaltrenner und Punkt als Tausender
    raw = raw.replace(".", "").replace(",", ".").replace("\xa0", "").replace(" ", "")
    raw = re.sub(r"[^\d.\-\+]", "", raw)
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _read_csv_bytes(content: bytes, fmt: str) -> pd.DataFrame:
    """Liest CSV-Bytes robust — probiert utf-8, dann latin-1. Überspringt DKB-Header-Zeilen."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except Exception:
            continue
    else:
        raise ValueError("CSV-Datei konnte nicht dekodiert werden.")

    # DKB-Auszüge haben oft Metazeilen am Anfang (Kontonummer, Zeitraum etc.)
    # Wir suchen die Header-Zeile anhand typischer Schlüsselwörter
    lines = text.splitlines()
    header_line = 0
    header_keywords = {"buchungsdatum", "belegdatum", "datum", "date", "wertstellung", "umsatz"}
    for i, line in enumerate(lines):
        if any(kw in line.lower() for kw in header_keywords):
            header_line = i
            break

    # Trenne Metadaten vom eigentlichen CSV
    csv_text = "\n".join(lines[header_line:])
    return pd.read_csv(io.StringIO(csv_text), sep=";", dtype=str, skipinitialspace=True)


# ── Dedup-Hash ────────────────────────────────────────────────────────────────

def compute_dedup_hash(row: NormalizedRow, account_name: str) -> str:
    """
    Stabiler Hash zur Duplikat-Erkennung.
    Basiert auf: Datum + Betrag (gerundet) + gekürzte Beschreibung + Gegenkonto + Konto.
    """
    parts = [
        str(row["booking_date"]),
        f"{row['amount']:.2f}",
        (row["raw_description"] or "")[:80].lower().strip(),
        (row["raw_counterparty"] or "")[:40].lower().strip(),
        account_name.lower().strip(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Haupt-Einstiegspunkt ──────────────────────────────────────────────────────

def parse_csv(content: bytes, account_name: str) -> tuple[str, list[NormalizedRow], list[str]]:
    """
    Parst CSV-Inhalt und gibt (format, rows, errors) zurück.
    rows: Liste normalisierter Dicts, jede Row hat dedup_hash gesetzt.
    errors: Liste von Fehlermeldungen (non-fatal).
    """
    errors: list[str] = []
    fmt = detect_format(content)
    logger.info("csv_parser.detected_format", extra={"fmt": fmt, "account": account_name})

    try:
        df = _read_csv_bytes(content, fmt)
    except Exception as e:
        return fmt, [], [f"CSV konnte nicht gelesen werden: {e}"]

    # Leere Zeilen raus
    df = df.dropna(how="all")

    try:
        if fmt == "dkb_giro":
            rows = _parse_dkb_giro(df)
        elif fmt == "dkb_visa":
            rows = _parse_dkb_visa(df)
        else:
            rows = _parse_generic(df)
    except ValueError as e:
        return fmt, [], [str(e)]
    except Exception as e:
        return fmt, [], [f"Unerwarteter Fehler beim Parsen: {e}"]

    # Dedup-Hash berechnen
    for row in rows:
        row["dedup_hash"] = compute_dedup_hash(row, account_name)

    if not rows:
        errors.append("Keine verwertbaren Zeilen gefunden.")

    logger.info("csv_parser.done", extra={"fmt": fmt, "rows": len(rows), "errors": len(errors)})
    return fmt, rows, errors
