"""Add reminders.read_at for the in-app notification center (REM-07, OPP-01).

The bell badge counts inbox reminders (REM-06) that the user has not seen yet.
"Read" is independent from "dismissed" (REM-05): reading only clears the badge,
dismissing removes the reminder from the inbox. Existing reminders start as
unread (NULL), which is the safe default: at worst the user sees a badge for
notifications that were already on screen before this migration.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reminders", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reminders", "read_at")
