"""Transactions, recurring rules and exchange rates (Fase 1).

Implements TXN-01..06, REC-01..05, FX-02/03, GLO-01/02/04.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-10
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurring_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount_is_estimate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT")),
        sa.Column(
            "payment_method_id",
            sa.Uuid(),
            sa.ForeignKey("payment_methods.id", ondelete="RESTRICT"),
        ),
        sa.Column("frequency", sa.String(10), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("max_occurrences", sa.Integer()),
        sa.Column("month_day", sa.Integer()),
        sa.Column("use_last_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_rule_amount_positive"),
        sa.CheckConstraint(
            "month_day IS NULL OR (month_day >= 1 AND month_day <= 31)",
            name="ck_rule_month_day",
        ),
        sa.CheckConstraint(
            "frequency IN ('weekly', 'biweekly', 'monthly', 'yearly')",
            name="ck_rule_frequency",
        ),
    )
    op.create_index("ix_recurring_rules_space_id", "recurring_rules", ["space_id"])

    op.create_table(
        "recurring_tombstones",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "rule_id",
            sa.Uuid(),
            sa.ForeignKey("recurring_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.UniqueConstraint("rule_id", "scheduled_date", name="uq_tombstone"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("notes", sa.Text()),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("fx_rate_to_base", sa.Numeric(20, 8)),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT")),
        sa.Column("expense_nature_override", sa.String(15)),
        sa.Column(
            "payment_method_id",
            sa.Uuid(),
            sa.ForeignKey("payment_methods.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "payment_method_to_id",
            sa.Uuid(),
            sa.ForeignKey("payment_methods.id", ondelete="RESTRICT"),
        ),
        sa.Column("credit_card_id", sa.Uuid()),
        sa.Column("installment_plan_id", sa.Uuid()),
        sa.Column(
            "recurring_rule_id",
            sa.Uuid(),
            sa.ForeignKey("recurring_rules.id", ondelete="SET NULL"),
        ),
        sa.Column("scheduled_date", sa.Date()),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("import_batch_id", sa.Uuid()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("profiles.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_txn_amount_positive"),
        sa.CheckConstraint("type IN ('expense', 'income', 'transfer')", name="ck_txn_type"),
        sa.UniqueConstraint("recurring_rule_id", "scheduled_date", name="uq_txn_recurrence"),
    )
    # PLAN §3: hot path is (space_id, date).
    op.create_index("ix_transactions_space_id", "transactions", ["space_id"])
    op.create_index("ix_transactions_date", "transactions", ["date"])
    op.create_index("ix_transactions_space_date", "transactions", ["space_id", "date"])

    op.create_table(
        "exchange_rates",
        sa.Column("base", sa.String(3), primary_key=True),
        sa.Column("quote", sa.String(3), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("is_carry_forward", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(30), nullable=False, server_default="banxico"),
    )


def downgrade() -> None:
    op.drop_table("exchange_rates")
    op.drop_table("transactions")
    op.drop_table("recurring_tombstones")
    op.drop_table("recurring_rules")
