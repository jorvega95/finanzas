"""Budgets (Fase 3). Implements PRE-01..PRE-04.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("alert_threshold", sa.Numeric(3, 2), nullable=False, server_default="0.80"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_budget_amount"),
        sa.CheckConstraint(
            "alert_threshold > 0 AND alert_threshold <= 1", name="ck_budget_threshold"
        ),
        sa.UniqueConstraint("space_id", "category_id", "month", name="uq_budget"),
    )
    op.create_index("ix_budgets_space_id", "budgets", ["space_id"])


def downgrade() -> None:
    op.drop_table("budgets")
