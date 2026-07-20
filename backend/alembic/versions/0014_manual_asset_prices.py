"""Manual asset prices scoped per space (INV-04/INV-04b).

Splits manual prices out of the global `asset_prices` cache: manual entries now
live in `manual_asset_prices (space_id, symbol)` so one space can no longer
overwrite (or permanently freeze) the price another space sees. The provider
cache stays global on purpose (INV-03: one batch per refresh for all symbols).

RLS scopes the new table by space membership, mirroring the domain tables from
0006 (only applies on PostgreSQL; tests run on SQLite via create_all).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_asset_prices",
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("symbol", sa.String(60), primary_key=True),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MXN"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # INV-04b: migrar los precios manuales preexistentes. La caché global no
    # sabía a qué espacio pertenecían, así que se copian a CADA espacio que
    # tenga un holding con ese símbolo (el predicado que ahora exige INV-04);
    # los símbolos sin dueño se dejan solo en la caché (ya no como "manual").
    op.execute(
        """
        INSERT INTO public.manual_asset_prices (space_id, symbol, price, currency, fetched_at)
        SELECT DISTINCT ia.space_id, ap.symbol, ap.price, ap.currency, ap.fetched_at
        FROM public.asset_prices ap
        JOIN public.holdings h ON h.asset_symbol = ap.symbol AND h.quantity > 0
        JOIN public.investment_accounts ia ON ia.id = h.account_id
        WHERE ap.source = 'manual'
        ON CONFLICT (space_id, symbol) DO NOTHING;
        """
    )
    # Las filas 'manual' huérfanas en la caché ya no deben tratarse como eternas.
    op.execute("DELETE FROM public.asset_prices WHERE source = 'manual';")

    op.execute("ALTER TABLE public.manual_asset_prices ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY manual_asset_prices_space_isolation ON public.manual_asset_prices
        USING (public.is_space_member(space_id));
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP POLICY IF EXISTS manual_asset_prices_space_isolation "
            "ON public.manual_asset_prices;"
        )
    op.drop_table("manual_asset_prices")
