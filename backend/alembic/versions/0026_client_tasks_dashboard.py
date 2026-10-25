"""Opt-in dashboard card and unit label for tasks paid (FAC-17).

- `billing_clients.show_tasks_on_dashboard` (default false; backfilled to
  true where a task_rate already exists, so the current card keeps showing).
- `billing_clients.task_unit_label` (plural noun shown with the count).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_clients", sa.Column("task_unit_label", sa.String(30)))
    op.add_column(
        "billing_clients",
        sa.Column(
            "show_tasks_on_dashboard", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.execute(
        "UPDATE billing_clients SET show_tasks_on_dashboard = true WHERE task_rate IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_billing_client_tasks_dashboard_rate",
        "billing_clients",
        "NOT show_tasks_on_dashboard OR task_rate IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_billing_client_tasks_dashboard_rate", "billing_clients", type_="check")
    op.drop_column("billing_clients", "show_tasks_on_dashboard")
    op.drop_column("billing_clients", "task_unit_label")
