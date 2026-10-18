"""Card front image for the visual card design (TAR-08).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("image", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cards", "image")
