from __future__ import annotations
"""Tests für CSV-Parser und Kategorisierer."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from app.finance.csv_parser import detect_format, parse_csv, compute_dedup_hash, _parse_amount, _parse_date
from app.finance.categorizer import categorize, normalize_merchant
from datetime import date


# ── Hilfsdaten ────────────────────────────────────────────────────────────────

DUMMY_CSV_PATH = os.path.join(os.path.dirname(__file__), "dummy_dkb_giro.csv")


def load_dummy() -> bytes:
    with open(DUMMY_CSV_PATH, "rb") as f:
        return f.read()


# ── Format-Erkennung ──────────────────────────────────────────────────────────

def test_detect_format_dkb_giro():
    content = load_dummy()
    fmt = detect_format(content)
    assert fmt == "dkb_giro"


def test_detect_format_generic():
    content = b"date,amount,description\n2026-01-01,-50.00,Test"
    fmt = detect_format(content)
    assert fmt == "generic"


# ── Parsing ───────────────────────────────────────────────────────────────────

def test_parse_csv_dkb_giro():
    content = load_dummy()
    fmt, rows, errors = parse_csv(content, "DKB Girokonto")
    assert fmt == "dkb_giro"
    assert len(rows) > 10
    assert len(errors) == 0
    # Alle rows haben booking_date
    assert all(isinstance(r["booking_date"], date) for r in rows)
    # Alle haben dedup_hash
    assert all("dedup_hash" in r for r in rows)


def test_parse_csv_amounts():
    content = load_dummy()
    _, rows, _ = parse_csv(content, "DKB Girokonto")
    amounts = [r["amount"] for r in rows]
    # Gehalt muss positiv sein
    incomes = [a for a in amounts if a > 0]
    assert len(incomes) >= 2  # Gehalt + Rückerstattung
    # Ausgaben müssen negativ sein
    expenses = [a for a in amounts if a < 0]
    assert len(expenses) > 10


def test_parse_amount_german_format():
    assert _parse_amount("2.800,00") == 2800.0
    assert _parse_amount("-67,34") == -67.34
    assert _parse_amount("+389,00") == 389.0
    assert _parse_amount("0") == 0.0


def test_parse_date_formats():
    assert _parse_date("01.04.2026") == date(2026, 4, 1)
    assert _parse_date("2026-04-01") == date(2026, 4, 1)
    assert _parse_date("") is None
    assert _parse_date("nan") is None


# ── Dedup-Hash ────────────────────────────────────────────────────────────────

def test_dedup_hash_stable():
    row = {
        "booking_date": date(2026, 4, 1),
        "amount": -67.34,
        "raw_description": "Einkauf",
        "raw_counterparty": "REWE SAGT DANKE",
    }
    h1 = compute_dedup_hash(row, "DKB Girokonto")
    h2 = compute_dedup_hash(row, "DKB Girokonto")
    assert h1 == h2
    assert len(h1) == 32


def test_dedup_hash_different_amounts():
    row1 = {"booking_date": date(2026, 4, 1), "amount": -67.34, "raw_description": "Test", "raw_counterparty": "REWE"}
    row2 = {"booking_date": date(2026, 4, 1), "amount": -67.35, "raw_description": "Test", "raw_counterparty": "REWE"}
    assert compute_dedup_hash(row1, "DKB") != compute_dedup_hash(row2, "DKB")


def test_no_duplicate_hashes_in_file():
    content = load_dummy()
    _, rows, _ = parse_csv(content, "DKB Girokonto")
    # Gleiche Transaktion (Perücke und Rückerstattung am gleichen Tag)
    # sind verschiedene Buchungen und sollten verschiedene Hashes haben
    hashes = [r["dedup_hash"] for r in rows]
    # Prüfen dass es insgesamt sehr wenige Kollisionen gibt
    unique_hashes = set(hashes)
    assert len(unique_hashes) >= len(hashes) - 1  # max 1 Kollision toleriert


# ── Kategorisierung ───────────────────────────────────────────────────────────

def test_categorize_rewe():
    cat, sub, conf, src = categorize("Einkauf", "REWE SAGT DANKE", -67.34)
    assert cat == "Lebensmittel"
    assert conf >= 0.8


def test_categorize_netflix():
    cat, sub, conf, src = categorize("Netflix Abo", "NETFLIX INTERNATIONAL", -17.99)
    assert cat == "Abos/Software"
    assert conf >= 0.8


def test_categorize_refund_positive():
    cat, sub, conf, src = categorize("Rueckerstattung Peruecke", "HAIRSHOP24 GMBH", +389.0)
    assert cat == "Rückerstattung"
    assert conf >= 0.9


def test_categorize_salary():
    cat, sub, conf, src = categorize("Gehalt April 2026", "ARBEITGEBER GMBH", +2800.0)
    assert cat == "Einkommen"


def test_categorize_bijou():
    cat, sub, conf, src = categorize("Schmuck Ohrring", "BIJOU BRIGITTE AG", -34.90)
    assert cat == "Klara/Styling"


def test_categorize_unknown():
    cat, sub, conf, src = categorize("Zahlung", "UNBEKANNTER HAENDLER XYZ123", -150.0)
    assert cat == "Unklar"
    assert conf == 0.0


def test_categorize_custom_rule():
    custom_rules = [{"pattern": "XYZ123", "category": "Technik/Projekte", "priority": 50, "field": "description"}]
    cat, sub, conf, src = categorize("Zahlung XYZ123", "UNBEKANNT", -150.0, db_rules=custom_rules)
    assert cat == "Technik/Projekte"
    assert src == "rule_db"


# ── Merchant-Normalisierung ───────────────────────────────────────────────────

def test_normalize_merchant():
    assert "REWE" in normalize_merchant("REWE SAGT DANKE 12345", "")
    assert len(normalize_merchant("", "")) > 0  # Kein leerer String


# ── Vollintegration ───────────────────────────────────────────────────────────

def test_full_parse_and_categorize():
    content = load_dummy()
    _, rows, _ = parse_csv(content, "DKB Girokonto")
    results = []
    for row in rows:
        cat, sub, conf, src = categorize(
            row.get("raw_description", ""),
            row.get("raw_counterparty", ""),
            row["amount"],
        )
        results.append({"cat": cat, "conf": conf})

    unklar = [r for r in results if r["cat"] == "Unklar"]
    klar = [r for r in results if r["cat"] != "Unklar"]

    # Mindestens 70% der Transaktionen sollten kategorisiert sein
    assert len(klar) / len(results) >= 0.70, f"Zu viele unklare: {len(unklar)}/{len(results)}"
