"""Per-user card ordering (TAR-07).

A `card_layouts` row holds one user's ordered list of card ids within a space
(one row per user+space). It's a personal UI preference, not shared domain data,
so RLS scopes it to the owning user (user_id = auth.uid()), not space membership.
RLS only applies on PostgreSQL (tests run on SQLite with create_all).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_layouts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "space_id", name="uq_card_layout_user_space"),
    )
    op.create_index("ix_card_layouts_user_id", "card_layouts", ["user_id"])
    op.create_index("ix_card_layouts_space_id", "card_layouts", ["space_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.card_layouts ENABLE ROW LEVEL SECURITY;")
        op.execute(
            """
            CREATE POLICY card_layouts_owner_only ON public.card_layouts
            USING (user_id = auth.uid());
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS card_layouts_owner_only ON public.card_layouts;")
    op.drop_table("card_layouts")
