"""Add semimonthly frequency to recurring rules (REC-06).

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "recurring_rules",
        "frequency",
        type_=sa.String(12),
        existing_type=sa.String(10),
        existing_nullable=False,
    )
    op.drop_constraint("ck_rule_frequency", "recurring_rules", type_="check")
    op.create_check_constraint(
        "ck_rule_frequency",
        "recurring_rules",
        "frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly', 'yearly')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_rule_frequency", "recurring_rules", type_="check")
    op.create_check_constraint(
        "ck_rule_frequency",
        "recurring_rules",
        "frequency IN ('weekly', 'biweekly', 'monthly', 'yearly')",
    )
    op.alter_column(
        "recurring_rules",
        "frequency",
        type_=sa.String(10),
        existing_type=sa.String(12),
        existing_nullable=False,
    )
