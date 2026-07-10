"""Persist TDC-14 opening_balance separately from computed_total (PEND-01).

Before this, a statement created from a manual opening balance (TDC-14) stored
that amount directly in computed_total. If a late charge or refund (TDC-06/
TDC-16) later got assigned to that same statement, recompute_statement_total
overwrote computed_total with only the itemized total, silently discarding
the manual amount. This adds a separate opening_balance column that
_raw_statement_total always adds back in, and backfills it for existing
statements that were created as a pure opening balance (closed, no itemized
transactions/installments yet).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-10
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("card_statements", sa.Column("opening_balance", sa.Numeric(14, 2), nullable=True))
    op.execute(
        """
        UPDATE card_statements AS s
        SET opening_balance = s.computed_total
        WHERE s.status = 'closed'
          AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.statement_id = s.id)
          AND NOT EXISTS (SELECT 1 FROM installments i WHERE i.statement_id = s.id)
        """
    )


def downgrade() -> None:
    op.drop_column("card_statements", "opening_balance")
