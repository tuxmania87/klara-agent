from __future__ import annotations
"""Finanz-Models: Transaktionen, Kategorie-Regeln, Budgets, importierte Dateien."""
from datetime import date, datetime
from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class FinanceFile(Base):
    """Bereits importierte Dateien — verhindert Doppel-Import."""
    __tablename__ = "finance_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    drive_file_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(512))
    account_name: Mapped[str] = mapped_column(String(256))
    detected_format: Mapped[str | None] = mapped_column(String(64))  # dkb_giro|dkb_visa|generic
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    import_errors: Mapped[str | None] = mapped_column(Text)  # JSON-Liste von Fehlern

    transactions: Mapped[list[Transaction]] = relationship(back_populates="source_file_obj")


class Transaction(Base):
    """Normalisierte Finanztransaktion."""
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("dedup_hash", name="uq_transaction_dedup_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Datumsfelder
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date | None] = mapped_column(Date)
    # Betrag
    amount: Mapped[float] = mapped_column(Float)          # negativ = Ausgabe, positiv = Einnahme
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    # Beschreibung (Rohdaten)
    raw_description: Mapped[str | None] = mapped_column(Text)
    raw_counterparty: Mapped[str | None] = mapped_column(String(512))
    # Normalisiert
    normalized_merchant: Mapped[str | None] = mapped_column(String(256), index=True)
    # Kategorisierung
    category: Mapped[str] = mapped_column(String(64), default="Unklar", index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64))
    category_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    category_source: Mapped[str] = mapped_column(String(32), default="unclassified")
    # rule|llm|manual|default
    # Konto
    account_name: Mapped[str] = mapped_column(String(256), index=True)
    # Quelle
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("finance_files.id"))
    source_row: Mapped[int | None] = mapped_column(Integer)
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Flags
    is_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    refund_for_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    is_subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    source_file_obj: Mapped[FinanceFile | None] = relationship(back_populates="transactions")


class CategoryRule(Base):
    """
    Regelbasierte Kategorisierung — Pattern auf raw_description oder normalized_merchant.
    Höhere priority gewinnt bei Konflikten.
    """
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(String(256))        # case-insensitive substring
    field: Mapped[str] = mapped_column(String(32), default="description")  # description|merchant
    category: Mapped[str] = mapped_column(String(64))
    subcategory: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(32), default="user")  # user|system


class Budget(Base):
    """Monatliches Budget pro Kategorie."""
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("category", "month_year", name="uq_budget_cat_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    month_year: Mapped[str] = mapped_column(String(7), index=True)  # "2026-05" oder "default"
    amount_limit: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
