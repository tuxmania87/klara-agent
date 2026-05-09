from __future__ import annotations
"""
Finance Service — orchestriert Import, Kategorisierung und Analysen.
Alle schweren Berechnungen laufen mit Python/SQL, kein LLM für Rohdaten.
"""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.finance import Budget, CategoryRule, FinanceFile, Transaction
from app.finance.csv_parser import parse_csv
from app.finance.categorizer import categorize, normalize_merchant

logger = logging.getLogger(__name__)


class FinanceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Import ────────────────────────────────────────────────────────────────

    async def list_drive_files(self) -> list[dict]:
        """Listet CSVs aus Google Drive. Markiert bereits importierte."""
        from app.integrations.google_drive import list_csv_files

        if not settings.GDRIVE_FINANCE_FOLDER_ID:
            return [{"error": "GDRIVE_FINANCE_FOLDER_ID nicht konfiguriert."}]

        drive_files = await asyncio.get_event_loop().run_in_executor(
            None, lambda: list_csv_files(settings.GDRIVE_FINANCE_FOLDER_ID)
        )

        # Bereits importierte IDs laden
        result = await self.db.execute(select(FinanceFile.drive_file_id))
        imported_ids = {r[0] for r in result.all()}

        out = []
        for f in drive_files:
            out.append({
                "id": f["id"],
                "name": f["name"],
                "modified": f.get("modifiedTime", ""),
                "already_imported": f["id"] in imported_ids,
            })
        return out

    async def import_file(self, drive_file_id: str, account_name: str | None = None, dry_run: bool = False) -> dict:
        """
        Importiert eine einzelne CSV-Datei aus Drive.
        dry_run=True: parst und gibt Vorschau zurück ohne zu speichern.
        """
        from app.integrations.google_drive import list_csv_files, download_csv

        # Bereits importiert?
        existing = await self.db.execute(
            select(FinanceFile).where(FinanceFile.drive_file_id == drive_file_id)
        )
        if existing.scalar_one_or_none():
            return {"status": "already_imported", "file_id": drive_file_id}

        # Dateiname ermitteln
        if not settings.GDRIVE_FINANCE_FOLDER_ID:
            return {"error": "GDRIVE_FINANCE_FOLDER_ID nicht konfiguriert."}

        files = await asyncio.get_event_loop().run_in_executor(
            None, lambda: list_csv_files(settings.GDRIVE_FINANCE_FOLDER_ID)
        )
        file_meta = next((f for f in files if f["id"] == drive_file_id), None)
        filename = file_meta["name"] if file_meta else drive_file_id
        account = account_name or settings.FINANCE_DEFAULT_ACCOUNT

        # Download
        content = await asyncio.get_event_loop().run_in_executor(
            None, lambda: download_csv(drive_file_id)
        )

        # Parsen
        fmt, rows, errors = parse_csv(content, account)

        if dry_run:
            return {
                "status": "dry_run",
                "filename": filename,
                "format": fmt,
                "rows_found": len(rows),
                "errors": errors,
                "sample": rows[:3] if rows else [],
            }

        if not rows and errors:
            return {"status": "error", "filename": filename, "errors": errors}

        # DB-Regeln für Kategorisierung laden
        db_rules = await self._load_rules()

        # FinanceFile anlegen
        finance_file = FinanceFile(
            drive_file_id=drive_file_id,
            filename=filename,
            account_name=account,
            detected_format=fmt,
            import_errors=json.dumps(errors) if errors else None,
        )
        self.db.add(finance_file)
        await self.db.flush()  # ID holen

        # Transaktionen speichern
        saved = 0
        skipped_dupes = 0
        for row in rows:
            # Dedup-Check
            existing_tx = await self.db.execute(
                select(Transaction).where(Transaction.dedup_hash == row["dedup_hash"])
            )
            if existing_tx.scalar_one_or_none():
                skipped_dupes += 1
                continue

            cat, subcat, conf, source = categorize(
                raw_description=row.get("raw_description", ""),
                raw_counterparty=row.get("raw_counterparty", ""),
                amount=row["amount"],
                db_rules=db_rules,
            )
            merchant = normalize_merchant(
                row.get("raw_counterparty", ""),
                row.get("raw_description", ""),
            )
            is_refund = cat == "Rückerstattung"

            tx = Transaction(
                booking_date=row["booking_date"],
                value_date=row.get("value_date"),
                amount=row["amount"],
                currency=row.get("currency", "EUR"),
                raw_description=row.get("raw_description"),
                raw_counterparty=row.get("raw_counterparty"),
                normalized_merchant=merchant,
                category=cat,
                subcategory=subcat,
                category_confidence=conf,
                category_source=source,
                account_name=account,
                source_file_id=finance_file.id,
                source_row=row.get("_source_row"),
                dedup_hash=row["dedup_hash"],
                is_refund=is_refund,
            )
            self.db.add(tx)
            saved += 1

        finance_file.row_count = saved
        await self.db.commit()

        logger.info("finance_service.import_done", extra={
            "file": filename, "saved": saved, "dupes": skipped_dupes
        })
        return {
            "status": "imported",
            "filename": filename,
            "format": fmt,
            "rows_saved": saved,
            "duplicates_skipped": skipped_dupes,
            "errors": errors,
        }

    async def import_new_files(self) -> dict:
        """Importiert alle noch nicht importierten Dateien aus Drive automatisch."""
        files = await self.list_drive_files()
        if isinstance(files, list) and files and "error" in files[0]:
            return files[0]

        new_files = [f for f in files if not f["already_imported"]]
        if not new_files:
            return {"status": "nothing_new", "message": "Keine neuen Dateien gefunden."}

        results = []
        for f in new_files:
            result = await self.import_file(f["id"])
            results.append(result)

        return {"status": "done", "imported": len(results), "details": results}

    # ── Kategorisierung ───────────────────────────────────────────────────────

    async def _load_rules(self) -> list[dict]:
        result = await self.db.execute(
            select(CategoryRule).order_by(CategoryRule.priority.desc())
        )
        rules = result.scalars().all()
        return [
            {"pattern": r.pattern, "field": r.field, "category": r.category,
             "subcategory": r.subcategory, "priority": r.priority}
            for r in rules
        ]

    async def add_rule(self, pattern: str, category: str, subcategory: str | None = None,
                       field: str = "description", priority: int = 50) -> dict:
        """Fügt eine neue Kategorisierungsregel hinzu und wendet sie sofort an."""
        rule = CategoryRule(
            pattern=pattern, category=category, subcategory=subcategory,
            field=field, priority=priority, created_by="user"
        )
        self.db.add(rule)
        await self.db.flush()

        # Bereits gespeicherte Transaktionen mit niedrigerer Konfidenz neu kategorisieren
        result = await self.db.execute(
            select(Transaction).where(Transaction.category_confidence < 0.95)
        )
        updated = 0
        for tx in result.scalars().all():
            field_text = (
                f"{tx.raw_description or ''} {tx.raw_counterparty or ''}"
                if field == "description" else (tx.raw_counterparty or "")
            )
            if pattern.lower() in field_text.lower():
                tx.category = category
                tx.subcategory = subcategory
                tx.category_confidence = 0.95
                tx.category_source = "rule_db"
                updated += 1

        await self.db.commit()
        return {"status": "rule_added", "pattern": pattern, "category": category, "transactions_updated": updated}

    async def get_unclear_transactions(self, limit: int = 20) -> list[dict]:
        """Transaktionen mit unklarer Kategorisierung."""
        result = await self.db.execute(
            select(Transaction)
            .where(or_(Transaction.category == "Unklar", Transaction.category_confidence < 0.5))
            .order_by(Transaction.booking_date.desc())
            .limit(limit)
        )
        txs = result.scalars().all()
        return [self._tx_to_dict(tx) for tx in txs]

    async def recategorize(self, transaction_id: int, category: str, subcategory: str | None = None) -> dict:
        """Manuelle Kategorisierungskorrektur."""
        result = await self.db.execute(select(Transaction).where(Transaction.id == transaction_id))
        tx = result.scalar_one_or_none()
        if not tx:
            return {"error": f"Transaktion {transaction_id} nicht gefunden."}
        tx.category = category
        tx.subcategory = subcategory
        tx.category_confidence = 1.0
        tx.category_source = "manual"
        await self.db.commit()
        return {"status": "updated", "transaction_id": transaction_id, "category": category}

    # ── Monatsreport ──────────────────────────────────────────────────────────

    async def monthly_report(self, year: int, month: int, account_name: str | None = None) -> dict:
        """
        Deterministischer Monatsreport — alle Berechnungen in Python/SQL.
        LLM bekommt nur Aggregat-Daten für den Kommentar.
        """
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)

        stmt = select(Transaction).where(
            and_(Transaction.booking_date >= start, Transaction.booking_date < end)
        )
        if account_name:
            stmt = stmt.where(Transaction.account_name == account_name)

        result = await self.db.execute(stmt)
        txs = list(result.scalars().all())

        if not txs:
            return {"error": f"Keine Transaktionen für {year}-{month:02d} gefunden."}

        income = sum(t.amount for t in txs if t.amount > 0 and not t.is_refund)
        expenses = sum(t.amount for t in txs if t.amount < 0)
        refunds = sum(t.amount for t in txs if t.is_refund and t.amount > 0)
        net_expenses = expenses + refunds  # Ausgaben nach Abzug Rückerstattungen

        # Ausgaben pro Kategorie (nur negative, ohne Rückerstattungen)
        cat_totals: dict[str, float] = defaultdict(float)
        for t in txs:
            if t.amount < 0 and not t.is_refund:
                cat_totals[t.category] += abs(t.amount)

        top_categories = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)[:8]

        # Größte Einzelbuchungen
        biggest = sorted([t for t in txs if t.amount < 0], key=lambda t: t.amount)[:5]

        # Abos
        subscriptions = [t for t in txs if t.is_subscription]

        # Unklar
        unclear_count = sum(1 for t in txs if t.category == "Unklar")

        return {
            "period": f"{year}-{month:02d}",
            "transaction_count": len(txs),
            "income_gross": round(income, 2),
            "expenses_gross": round(abs(expenses), 2),
            "refunds": round(refunds, 2),
            "expenses_net": round(abs(net_expenses), 2),
            "balance": round(income + expenses + refunds, 2),
            "top_categories": [{"category": c, "amount": round(a, 2)} for c, a in top_categories],
            "biggest_expenses": [self._tx_to_dict(t) for t in biggest],
            "subscription_count": len(subscriptions),
            "unclear_count": unclear_count,
        }

    async def compare_months(self, year1: int, month1: int, year2: int, month2: int) -> dict:
        """Vergleicht zwei Monate Kategorie für Kategorie."""
        r1 = await self.monthly_report(year1, month1)
        r2 = await self.monthly_report(year2, month2)
        if "error" in r1 or "error" in r2:
            return {"r1": r1, "r2": r2}

        cats1 = {c["category"]: c["amount"] for c in r1["top_categories"]}
        cats2 = {c["category"]: c["amount"] for c in r2["top_categories"]}
        all_cats = set(cats1) | set(cats2)

        changes = []
        for cat in all_cats:
            a1, a2 = cats1.get(cat, 0), cats2.get(cat, 0)
            diff = a2 - a1
            pct = (diff / a1 * 100) if a1 else None
            changes.append({"category": cat, "month1": a1, "month2": a2,
                            "diff": round(diff, 2), "pct_change": round(pct, 1) if pct else None})
        changes.sort(key=lambda x: abs(x["diff"]), reverse=True)

        return {
            "period1": r1["period"], "period2": r2["period"],
            "income_diff": round(r2["income_gross"] - r1["income_gross"], 2),
            "expenses_diff": round(r2["expenses_gross"] - r1["expenses_gross"], 2),
            "balance_diff": round(r2["balance"] - r1["balance"], 2),
            "category_changes": changes[:10],
        }

    # ── Abos ─────────────────────────────────────────────────────────────────

    async def detect_subscriptions(self) -> dict:
        """
        Erkennt wiederkehrende Zahlungen anhand: gleicher Händler + ähnlicher Betrag + regelmäßiger Abstand.
        Einfacher deterministischer Ansatz: Gruppen nach normalized_merchant.
        """
        result = await self.db.execute(
            select(Transaction)
            .where(Transaction.amount < 0)
            .order_by(Transaction.normalized_merchant, Transaction.booking_date)
        )
        txs = list(result.scalars().all())

        # Gruppiere nach Merchant
        merchant_groups: dict[str, list[Transaction]] = defaultdict(list)
        for tx in txs:
            key = (tx.normalized_merchant or "Unbekannt").lower()
            merchant_groups[key].append(tx)

        subscriptions = []
        for merchant, group in merchant_groups.items():
            if len(group) < 2:
                continue
            amounts = [abs(t.amount) for t in group]
            avg_amount = sum(amounts) / len(amounts)
            # Ähnliche Beträge (max 10% Abweichung)
            if max(amounts) - min(amounts) > avg_amount * 0.15:
                continue
            # Regelmäßiger Abstand
            dates = sorted([t.booking_date for t in group])
            gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
            avg_gap = sum(gaps) / len(gaps)
            # Monatlich (25-35 Tage) oder jährlich (340-380 Tage)
            is_monthly = 20 <= avg_gap <= 40
            is_yearly = 340 <= avg_gap <= 390
            if not (is_monthly or is_yearly):
                continue
            subscriptions.append({
                "merchant": group[0].normalized_merchant or merchant,
                "amount_avg": round(avg_amount, 2),
                "interval": "monatlich" if is_monthly else "jährlich",
                "occurrences": len(group),
                "last_date": str(dates[-1]),
                "category": group[0].category,
            })

        # Abos in DB markieren
        subscription_merchants = {s["merchant"].lower() for s in subscriptions}
        result2 = await self.db.execute(select(Transaction))
        for tx in result2.scalars().all():
            merchant_key = (tx.normalized_merchant or "").lower()
            if merchant_key in subscription_merchants and not tx.is_subscription:
                tx.is_subscription = True
        await self.db.commit()

        monthly_total = sum(
            s["amount_avg"] for s in subscriptions if s["interval"] == "monatlich"
        )
        yearly_total = sum(
            s["amount_avg"] / 12 for s in subscriptions if s["interval"] == "jährlich"
        )

        return {
            "subscription_count": len(subscriptions),
            "monthly_total_estimate": round(monthly_total + yearly_total, 2),
            "subscriptions": sorted(subscriptions, key=lambda x: x["amount_avg"], reverse=True),
        }

    # ── Budget ────────────────────────────────────────────────────────────────

    async def set_budget(self, category: str, amount: float, month_year: str = "default") -> dict:
        result = await self.db.execute(
            select(Budget).where(Budget.category == category, Budget.month_year == month_year)
        )
        budget = result.scalar_one_or_none()
        if budget:
            budget.amount_limit = amount
        else:
            budget = Budget(category=category, month_year=month_year, amount_limit=amount)
            self.db.add(budget)
        await self.db.commit()
        return {"status": "set", "category": category, "limit": amount, "month_year": month_year}

    async def budget_status(self, year: int, month: int) -> list[dict]:
        month_year = f"{year}-{month:02d}"
        # Ausgaben pro Kategorie
        report = await self.monthly_report(year, month)
        if "error" in report:
            return [{"error": report["error"]}]
        cat_spent = {c["category"]: c["amount"] for c in report["top_categories"]}

        # Budgets: monats-spezifisch, dann default
        result = await self.db.execute(
            select(Budget).where(Budget.month_year.in_([month_year, "default"]))
        )
        budgets_raw = list(result.scalars().all())
        # monats-spezifisch gewinnt
        budgets: dict[str, float] = {}
        for b in sorted(budgets_raw, key=lambda x: x.month_year):
            budgets[b.category] = b.amount_limit

        # Wie viel Monat ist schon vorbei?
        today = date.today()
        days_in_month = (date(year, month % 12 + 1, 1) - date(year, month, 1)).days if month < 12 else 31
        days_passed = min((today - date(year, month, 1)).days + 1, days_in_month)
        month_progress = days_passed / days_in_month

        status = []
        for cat, limit in budgets.items():
            spent = cat_spent.get(cat, 0)
            pct = spent / limit * 100 if limit else 0
            status.append({
                "category": cat,
                "budget": limit,
                "spent": round(spent, 2),
                "remaining": round(limit - spent, 2),
                "pct_used": round(pct, 1),
                "month_progress_pct": round(month_progress * 100, 1),
                "on_track": pct <= month_progress * 100 + 10,
            })
        return sorted(status, key=lambda x: x["pct_used"], reverse=True)

    # ── Rückerstattungen ──────────────────────────────────────────────────────

    async def refund_analysis(self, months_back: int = 3) -> dict:
        """Zeigt offene und gematche Rückerstattungen."""
        from datetime import timedelta
        since = date.today() - timedelta(days=months_back * 31)

        result = await self.db.execute(
            select(Transaction)
            .where(Transaction.booking_date >= since)
            .where(or_(Transaction.is_refund == True, Transaction.amount > 0))  # noqa
            .order_by(Transaction.booking_date.desc())
        )
        refunds = [t for t in result.scalars().all() if t.amount > 0]

        result2 = await self.db.execute(
            select(Transaction)
            .where(Transaction.booking_date >= since)
            .where(Transaction.amount < 0)
            .order_by(Transaction.amount)
        )
        big_expenses = [t for t in result2.scalars().all() if abs(t.amount) > 50]

        return {
            "refunds_found": len(refunds),
            "refunds_total": round(sum(t.amount for t in refunds), 2),
            "refunds": [self._tx_to_dict(t) for t in refunds[:10]],
            "large_expenses_possibly_refunded": [
                self._tx_to_dict(t) for t in big_expenses[:5]
            ],
        }

    # ── Ausreißer ─────────────────────────────────────────────────────────────

    async def outliers(self, year: int, month: int) -> dict:
        """Findet ungewöhnliche Buchungen im Monat."""
        start = date(year, month, 1)
        end = date(year, month % 12 + 1, 1) if month < 12 else date(year + 1, 1, 1)

        result = await self.db.execute(
            select(Transaction).where(
                and_(Transaction.booking_date >= start, Transaction.booking_date < end)
            )
        )
        txs = list(result.scalars().all())
        if not txs:
            return {"error": "Keine Transaktionen gefunden."}

        amounts = [abs(t.amount) for t in txs if t.amount < 0]
        if not amounts:
            return {"outliers": []}
        avg = sum(amounts) / len(amounts)
        threshold = max(avg * 3, 200)  # 3x Durchschnitt oder mind. 200€

        high = [t for t in txs if abs(t.amount) > threshold and t.amount < 0]
        unclear = [t for t in txs if t.category == "Unklar"]
        new_merchants_result = await self.db.execute(
            select(Transaction.normalized_merchant)
            .where(Transaction.booking_date < start)
            .distinct()
        )
        known_merchants = {r[0] for r in new_merchants_result.all()}
        new_merchants = [t for t in txs if t.normalized_merchant not in known_merchants and t.amount < 0]

        return {
            "avg_expense": round(avg, 2),
            "outlier_threshold": round(threshold, 2),
            "high_expenses": [self._tx_to_dict(t) for t in high],
            "unclear_category": [self._tx_to_dict(t) for t in unclear[:10]],
            "new_merchants": [self._tx_to_dict(t) for t in new_merchants[:10]],
        }

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────

    async def list_imported_files(self) -> list[dict]:
        result = await self.db.execute(
            select(FinanceFile).order_by(FinanceFile.imported_at.desc())
        )
        files = result.scalars().all()
        return [
            {"id": f.id, "filename": f.filename, "account": f.account_name,
             "format": f.detected_format, "rows": f.row_count,
             "imported_at": str(f.imported_at)}
            for f in files
        ]

    def _tx_to_dict(self, t: Transaction) -> dict:
        return {
            "id": t.id,
            "date": str(t.booking_date),
            "amount": t.amount,
            "merchant": t.normalized_merchant,
            "description": (t.raw_description or "")[:80],
            "category": t.category,
            "subcategory": t.subcategory,
            "confidence": t.category_confidence,
            "is_refund": t.is_refund,
            "is_subscription": t.is_subscription,
        }
