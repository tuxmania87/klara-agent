"""Finance tables: transactions, category_rules, budgets, finance_files

Revision ID: 0004_finance
Revises: 0003_triage_reminders_cases
Create Date: 2026-05-09
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0004_finance"
down_revision: Union[str, None] = "0003_triage_reminders_cases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("drive_file_id", sa.String(256), nullable=False, unique=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("account_name", sa.String(256), nullable=False),
        sa.Column("detected_format", sa.String(64), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("import_errors", sa.Text(), nullable=True),
    )
    op.create_index("ix_finance_files_drive_file_id", "finance_files", ["drive_file_id"], unique=True)

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="EUR"),
        sa.Column("raw_description", sa.Text(), nullable=True),
        sa.Column("raw_counterparty", sa.String(512), nullable=True),
        sa.Column("normalized_merchant", sa.String(256), nullable=True),
        sa.Column("category", sa.String(64), nullable=False, server_default="Unklar"),
        sa.Column("subcategory", sa.String(64), nullable=True),
        sa.Column("category_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("category_source", sa.String(32), nullable=False, server_default="unclassified"),
        sa.Column("account_name", sa.String(256), nullable=False),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("finance_files.id"), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("dedup_hash", sa.String(64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_refund", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("refund_for_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("is_subscription", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_outlier", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_internal_transfer", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("dedup_hash", name="uq_transaction_dedup_hash"),
    )
    op.create_index("ix_transactions_booking_date", "transactions", ["booking_date"])
    op.create_index("ix_transactions_category", "transactions", ["category"])
    op.create_index("ix_transactions_merchant", "transactions", ["normalized_merchant"])
    op.create_index("ix_transactions_account", "transactions", ["account_name"])

    op.create_table(
        "category_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pattern", sa.String(256), nullable=False),
        sa.Column("field", sa.String(32), nullable=False, server_default="description"),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("subcategory", sa.String(64), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(32), nullable=False, server_default="user"),
    )

    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("month_year", sa.String(7), nullable=False, server_default="default"),
        sa.Column("amount_limit", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("category", "month_year", name="uq_budget_cat_month"),
    )


def downgrade() -> None:
    op.drop_table("budgets")
    op.drop_table("category_rules")
    op.drop_index("ix_transactions_account", table_name="transactions")
    op.drop_index("ix_transactions_merchant", table_name="transactions")
    op.drop_index("ix_transactions_category", table_name="transactions")
    op.drop_index("ix_transactions_booking_date", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_finance_files_drive_file_id", table_name="finance_files")
    op.drop_table("finance_files")
