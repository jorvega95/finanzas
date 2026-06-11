"""Credit cards, statements, MSI plans and reminders (Fase 2).

Implements TDC-01..12, MSI-01..08, REM-01..04; adds transactions.statement_id.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("alias", sa.String(60), nullable=False),
        sa.Column("bank", sa.String(60), nullable=False),
        sa.Column("network", sa.String(20), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MXN"),
        sa.Column("credit_limit", sa.Numeric(14, 2)),
        sa.Column("statement_day", sa.Integer()),
        sa.Column("statement_day_is_last", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cutoff_day_policy", sa.String(12), nullable=False, server_default="include"),
        sa.Column("payment_due_days", sa.Integer()),
        sa.Column("payment_day", sa.Integer()),
        sa.Column("payment_day_is_last", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reminder_days", sa.JSON(), nullable=False),
        sa.Column("color", sa.String(20)),
        sa.Column("icon", sa.String(40)),
        sa.Column("payment_method_id", sa.Uuid()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "statement_day_is_last OR (statement_day >= 1 AND statement_day <= 28)",
            name="ck_card_statement_day",
        ),
        sa.CheckConstraint(
            "(payment_due_days IS NOT NULL) != (payment_day IS NOT NULL OR payment_day_is_last)",
            name="ck_card_payment_rule",
        ),
    )
    op.create_index("ix_credit_cards_space_id", "credit_cards", ["space_id"])

    op.create_table(
        "card_statements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "credit_card_id",
            sa.Uuid(),
            sa.ForeignKey("credit_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("computed_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("applied_credit", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("paid_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(15), nullable=False, server_default="open"),
        sa.CheckConstraint("period_start <= period_end", name="ck_statement_period"),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'paid', 'partially_paid')",
            name="ck_statement_status",
        ),
        sa.UniqueConstraint("credit_card_id", "period_end", name="uq_statement_period"),
    )
    op.create_index("ix_card_statements_space_id", "card_statements", ["space_id"])
    op.create_index("ix_card_statements_card", "card_statements", ["credit_card_id"])

    op.create_table(
        "installment_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "credit_card_id",
            sa.Uuid(),
            sa.ForeignKey("credit_cards.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("monthly_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("months >= 2 AND months <= 60", name="ck_plan_months"),
        sa.CheckConstraint("total_amount > 0", name="ck_plan_total_positive"),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'settled_early')", name="ck_plan_status"
        ),
    )
    op.create_index("ix_installment_plans_space_id", "installment_plans", ["space_id"])

    op.create_table(
        "installments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("installment_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("estimated_charge_date", sa.Date(), nullable=False),
        sa.Column(
            "statement_id", sa.Uuid(), sa.ForeignKey("card_statements.id", ondelete="SET NULL")
        ),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.CheckConstraint("amount > 0", name="ck_installment_amount"),
        sa.CheckConstraint(
            "status IN ('pending', 'charged', 'paid', 'canceled')",
            name="ck_installment_status",
        ),
        sa.UniqueConstraint("plan_id", "number", name="uq_installment_number"),
    )

    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(15), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("offset_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fire_at", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('card_due', 'budget_alert', 'custom')", name="ck_reminder_kind"
        ),
        sa.CheckConstraint("channel IN ('in_app', 'email')", name="ck_reminder_channel"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'canceled', 'failed')", name="ck_reminder_status"
        ),
        sa.UniqueConstraint("kind", "ref_id", "offset_days", "channel", name="uq_reminder"),
    )
    op.create_index("ix_reminders_space_id", "reminders", ["space_id"])
    op.create_index("ix_reminders_fire_at", "reminders", ["fire_at"])

    op.add_column("transactions", sa.Column("statement_id", sa.Uuid()))
    op.create_index("ix_transactions_statement", "transactions", ["statement_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_statement", table_name="transactions")
    op.drop_column("transactions", "statement_id")
    op.drop_table("reminders")
    op.drop_table("installments")
    op.drop_table("installment_plans")
    op.drop_table("card_statements")
    op.drop_table("credit_cards")
