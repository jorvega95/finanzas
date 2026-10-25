"""Banxico exchange-rate page URL in billing settings (FAC-06/FAC-14).

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-24
"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_settings", sa.Column("banxico_fx_url", sa.String(500)))


def downgrade() -> None:
    op.drop_column("billing_settings", "banxico_fx_url")
