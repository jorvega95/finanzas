"""Commitments with vendors: total agreed, abonos and payment schedule (CXP-01..08).

- New `commitments` and `commitment_payments` tables.
- `transactions.commitment_id` (an expense that is an abono, CXP-03).
- Reminder kind `commitment_due` (CXP-08).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "commitments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("events.id", ondelete="RESTRICT")),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("paid_before_tracking", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("due_date", sa.Date()),
        sa.Column("notes", sa.Text()),
        sa.Column("is_canceled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("total_amount > 0", name="ck_commitment_total_positive"),
        sa.CheckConstraint(
            "paid_before_tracking >= 0 AND paid_before_tracking <= total_amount",
            name="ck_commitment_paid_before",
        ),
    )
    op.create_index("ix_commitments_space_id", "commitments", ["space_id"])
    op.create_index("ix_commitments_event_id", "commitments", ["event_id"])

    op.create_table(
        "commitment_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "commitment_id",
            sa.Uuid(),
            sa.ForeignKey("commitments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("amount > 0", name="ck_commitment_payment_positive"),
    )
    op.create_index(
        "ix_commitment_payments_commitment_id", "commitment_payments", ["commitment_id"]
    )

    op.add_column("transactions", sa.Column("commitment_id", sa.Uuid()))
    op.create_foreign_key(
        "transactions_commitment_id_fkey",
        "transactions",
        "commitments",
        ["commitment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_transactions_commitment_id", "transactions", ["commitment_id"])

    op.drop_constraint("ck_reminder_kind", "reminders", type_="check")
    op.create_check_constraint(
        "ck_reminder_kind",
        "reminders",
        "kind IN ('card_due', 'budget_alert', 'commitment_due', 'custom')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM reminders WHERE kind = 'commitment_due'")
    op.drop_constraint("ck_reminder_kind", "reminders", type_="check")
    op.create_check_constraint(
        "ck_reminder_kind", "reminders", "kind IN ('card_due', 'budget_alert', 'custom')"
    )
    op.drop_index("ix_transactions_commitment_id", table_name="transactions")
    op.drop_constraint("transactions_commitment_id_fkey", "transactions", type_="foreignkey")
    op.drop_column("transactions", "commitment_id")
    op.drop_table("commitment_payments")
    op.drop_table("commitments")
