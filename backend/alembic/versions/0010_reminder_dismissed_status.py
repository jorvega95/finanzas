"""Add 'dismissed' to reminder status (REM-05: soft-delete by user).

The ck_reminder_status CHECK was created in 0003 with only
('pending', 'sent', 'canceled', 'failed'). This widens it to include
'dismissed' so users can soft-delete in-app notifications.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-18
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_STATUS_NEW = "'pending', 'sent', 'canceled', 'failed', 'dismissed'"
_STATUS_OLD = "'pending', 'sent', 'canceled', 'failed'"


def upgrade() -> None:
    op.drop_constraint("ck_reminder_status", "reminders", type_="check")
    op.create_check_constraint("ck_reminder_status", "reminders", f"status IN ({_STATUS_NEW})")


def downgrade() -> None:
    # Revert dismissed rows before narrowing the constraint.
    op.execute("UPDATE reminders SET status = 'canceled' WHERE status = 'dismissed'")
    op.drop_constraint("ck_reminder_status", "reminders", type_="check")
    op.create_check_constraint("ck_reminder_status", "reminders", f"status IN ({_STATUS_OLD})")
