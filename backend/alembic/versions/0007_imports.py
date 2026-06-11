"""Import batches (Fase 6). Implements IMP-01..IMP-06.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source", sa.String(60), nullable=False, server_default="csv"),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(25), nullable=False, server_default="confirmed"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'rolled_back', 'partially_rolled_back')",
            name="ck_import_status",
        ),
    )
    op.create_index("ix_import_batches_space_id", "import_batches", ["space_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.import_batches ENABLE ROW LEVEL SECURITY;")
        op.execute(
            """
            CREATE POLICY import_batches_space_isolation ON public.import_batches
            USING (public.is_space_member(space_id));
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS import_batches_space_isolation ON public.import_batches;")
    op.drop_table("import_batches")
