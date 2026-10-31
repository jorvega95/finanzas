"""Weekend adjustment for recurring rules (REC-15).

- `recurring_rules.weekend_adjust` (default false): a Saturday/Sunday
  occurrence moves back to the previous Friday.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recurring_rules",
        sa.Column("weekend_adjust", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("recurring_rules", "weekend_adjust")
