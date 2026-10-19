"""Events: group transactions of something extraordinary (EVT-01, EVT-02).

- New `events` table (per space, unique name, optional date/budget, soft-delete).
- `transactions.event_id` (nullable, at most one event per transaction).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_normalized", sa.String(80), nullable=False),
        sa.Column("date", sa.Date()),
        sa.Column("budget", sa.Numeric(14, 2)),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("space_id", "name_normalized", name="uq_event_name"),
        sa.CheckConstraint("budget IS NULL OR budget > 0", name="ck_event_budget_positive"),
    )
    op.create_index("ix_events_space_id", "events", ["space_id"])

    op.add_column("transactions", sa.Column("event_id", sa.Uuid()))
    op.create_foreign_key(
        "transactions_event_id_fkey",
        "transactions",
        "events",
        ["event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_transactions_event_id", "transactions", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_event_id", table_name="transactions")
    op.drop_constraint("transactions_event_id_fkey", "transactions", type_="foreignkey")
    op.drop_column("transactions", "event_id")
    op.drop_index("ix_events_space_id", table_name="events")
    op.drop_table("events")
