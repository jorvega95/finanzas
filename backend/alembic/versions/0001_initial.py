"""Initial schema: profiles, spaces, space_members, categories, payment_methods.

Implements ESP-01/02/03, CAT-01..03, GLO-04, GLO-05 (space_id everywhere),
FX-01 (base_currency from day one), GLO-02 (space timezone).

Revision ID: 0001
Revises:
Create Date: 2026-06-10
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("default_space_id", sa.Uuid()),
        sa.Column("locale", sa.String(10), nullable=False, server_default="es-MX"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="MXN"),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="America/Mexico_City"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("type IN ('personal', 'shared')", name="ck_space_type"),
    )

    op.create_table(
        "space_members",
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_member_role"),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("name_normalized", sa.String(60), nullable=False),
        sa.Column("icon", sa.String(40)),
        sa.Column("color", sa.String(20)),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("expense_nature", sa.String(15)),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('expense', 'income')", name="ck_category_kind"),
        sa.CheckConstraint(
            "expense_nature IN ('fixed', 'variable', 'discretionary')",
            name="ck_expense_nature",
        ),
        sa.UniqueConstraint("space_id", "kind", "name_normalized", name="uq_category_name"),
    )
    op.create_index("ix_categories_space_id", "categories", ["space_id"])

    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("name_normalized", sa.String(60), nullable=False),
        sa.Column("type", sa.String(15), nullable=False),
        sa.Column("credit_card_id", sa.Uuid()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "type IN ('cash', 'debit', 'credit_card', 'transfer', 'other')",
            name="ck_payment_method_type",
        ),
        sa.UniqueConstraint("space_id", "name_normalized", name="uq_payment_method_name"),
    )
    op.create_index("ix_payment_methods_space_id", "payment_methods", ["space_id"])


def downgrade() -> None:
    op.drop_table("payment_methods")
    op.drop_table("categories")
    op.drop_table("space_members")
    op.drop_table("spaces")
    op.drop_table("profiles")
