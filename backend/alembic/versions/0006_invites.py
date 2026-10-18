"""Space invites (Fase 5).

Implements ESP-04 (invites). Space isolation (GLO-05) is enforced by FastAPI.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_invite_role"),
    )
    op.create_index("ix_space_invites_space_id", "space_invites", ["space_id"])


def downgrade() -> None:
    op.drop_table("space_invites")
