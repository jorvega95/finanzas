"""Amount paid per task on billing clients (FAC-11).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-24
"""

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_clients", sa.Column("task_rate", sa.Numeric(14, 2)))
    op.create_check_constraint(
        "ck_billing_client_task_rate", "billing_clients", "task_rate IS NULL OR task_rate > 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_billing_client_task_rate", "billing_clients", type_="check")
    op.drop_column("billing_clients", "task_rate")
