"""Investments and net worth (Fase 4). Implements INV-01..06, PAT-01.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investment_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(15), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('crypto', 'stocks', 'fixed_income', 'other')", name="ck_account_kind"
        ),
    )
    op.create_index("ix_investment_accounts_space_id", "investment_accounts", ["space_id"])

    op.create_table(
        "holdings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("investment_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_symbol", sa.String(60), nullable=False),
        sa.Column("asset_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False),  # INV-01
        sa.Column("avg_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("realized_pnl", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_holding_quantity"),
        sa.UniqueConstraint("account_id", "asset_symbol", name="uq_holding_symbol"),
    )

    op.create_table(
        "investment_movements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "holding_id",
            sa.Uuid(),
            sa.ForeignKey("holdings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False),
        sa.Column("price", sa.Numeric(20, 8)),
        sa.Column("realized_pnl", sa.Numeric(14, 2)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_movement_quantity"),
        sa.CheckConstraint(
            "type IN ('buy', 'sell', 'deposit', 'withdraw')", name="ck_movement_type"
        ),
    )

    op.create_table(
        "asset_prices",
        sa.Column("symbol", sa.String(60), primary_key=True),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="coingecko"),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="snapshot"),
        sa.UniqueConstraint("space_id", "date", name="uq_portfolio_snapshot"),
    )
    op.create_index("ix_portfolio_snapshots_space_id", "portfolio_snapshots", ["space_id"])

    op.create_table(
        "net_worth_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("assets", sa.Numeric(14, 2), nullable=False),
        sa.Column("liabilities", sa.Numeric(14, 2), nullable=False),
        sa.Column("net_worth", sa.Numeric(14, 2), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.UniqueConstraint("space_id", "date", name="uq_networth_snapshot"),
    )
    op.create_index("ix_net_worth_snapshots_space_id", "net_worth_snapshots", ["space_id"])


def downgrade() -> None:
    op.drop_table("net_worth_snapshots")
    op.drop_table("portfolio_snapshots")
    op.drop_table("asset_prices")
    op.drop_table("investment_movements")
    op.drop_table("holdings")
    op.drop_table("investment_accounts")
