"""Triage, erweiterte Notizen, Reminders, Cases

Revision ID: 0003_triage_reminders_cases
Revises: 0002_notes
Create Date: 2026-05-09
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0003_triage_reminders_cases"
down_revision: Union[str, None] = "0002_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Triage-Felder auf emails ───────────────────────────────────────────
    # triage_label: urgent | important | info | later | needs_reply |
    #               needs_appointment | needs_followup | needs_clarification
    op.add_column("emails", sa.Column("triage_label", sa.String(32), nullable=True))
    op.add_column("emails", sa.Column("triage_reason", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("due_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("emails", sa.Column("involved_people", sa.Text(), nullable=True))  # JSON
    op.add_column("emails", sa.Column("draft_reply", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("tone", sa.String(32), nullable=True))  # work|authority|school|private|social

    # ── Erweiterte Notizen ─────────────────────────────────────────────────
    # category: task | idea | shopping | kids | case | tech | routine | template
    # status: open | done | archived
    op.add_column("notes", sa.Column("category", sa.String(32), nullable=True))
    op.add_column("notes", sa.Column("status", sa.String(16), nullable=True, server_default="open"))
    op.add_column("notes", sa.Column("due_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notes", sa.Column("source", sa.String(64), nullable=True))   # email_id, telegram, manual

    # ── Reminders ─────────────────────────────────────────────────────────
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        # Optional: Bezug zu Email oder Notiz
        sa.Column("source_email_id", sa.Integer(), nullable=True),
        sa.Column("source_note_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])
    op.create_index("ix_reminders_remind_at", "reminders", ["remind_at"])

    # ── Cases (Chronologien) ───────────────────────────────────────────────
    op.create_table(
        "cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),  # open|resolved|waiting
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cases_user_id", "cases", ["user_id"])

    op.create_table(
        "case_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("happened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(64), nullable=True),          # email, telegram, manual
        sa.Column("involved", sa.String(512), nullable=True),        # Personen/Orgs
        sa.Column("open_questions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])


def downgrade() -> None:
    op.drop_table("case_events")
    op.drop_table("cases")
    op.drop_index("ix_reminders_remind_at", table_name="reminders")
    op.drop_index("ix_reminders_user_id", table_name="reminders")
    op.drop_table("reminders")
    for col in ["triage_label", "triage_reason", "due_date", "involved_people", "draft_reply", "tone"]:
        op.drop_column("emails", col)
    for col in ["category", "status", "due_date", "source"]:
        op.drop_column("notes", col)
