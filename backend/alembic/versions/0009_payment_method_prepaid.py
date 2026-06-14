"""Allow 'prepaid' payment method type (TAR-03/CAT-07).

Migration 0008 added the `prepaid` PaymentMethodType (for vales/gift cards) but
did not widen the `ck_payment_method_type` CHECK created in 0001, so creating a
prepaid card's linked method failed against Postgres. This widens it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-13
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_TYPES = "'cash', 'debit', 'credit_card', 'prepaid', 'transfer', 'other'"
_TYPES_OLD = "'cash', 'debit', 'credit_card', 'transfer', 'other'"


def upgrade() -> None:
    op.drop_constraint("ck_payment_method_type", "payment_methods", type_="check")
    op.create_check_constraint("ck_payment_method_type", "payment_methods", f"type IN ({_TYPES})")


def downgrade() -> None:
    op.drop_constraint("ck_payment_method_type", "payment_methods", type_="check")
    op.create_check_constraint(
        "ck_payment_method_type", "payment_methods", f"type IN ({_TYPES_OLD})"
    )
