"""Personal loans: the `loan` account behavior and the "Regalos recibidos" income category.

Implements TAR-11, CAT-02, CAT-08:

- `account_types.behavior` accepts `loan`.
- Every space gets a "Préstamo personal" account type (behavior `loan`) and a
  "Regalos recibidos" income category (cash gifts and loan forgiveness), unless
  it already has them.

Postgres only (GLO-07). Downgrade is not supported: restore the backup taken
before upgrading (GLO-08, scripts/local/backup.sh).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19
"""

import uuid

import sqlalchemy as sa

from alembic import op
from app.core.text import normalize_name

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

LOAN_TYPE_NAME = "Préstamo personal"
LOAN_TYPE_FALLBACK = "Préstamos"  # if the user already named another type that way
GIFTS_CATEGORY = "Regalos recibidos"


def _ensure_loan_type(bind: sa.Connection, space_id: uuid.UUID, created_by: uuid.UUID) -> None:
    has_loan = bind.execute(
        sa.text("SELECT 1 FROM account_types WHERE space_id = :s AND behavior = 'loan'"),
        {"s": space_id},
    ).first()
    if has_loan is not None:
        return
    for name in (LOAN_TYPE_NAME, LOAN_TYPE_FALLBACK):
        taken = bind.execute(
            sa.text("SELECT 1 FROM account_types WHERE space_id = :s AND name_normalized = :n"),
            {"s": space_id, "n": normalize_name(name)},
        ).first()
        if taken is None:
            bind.execute(
                sa.text(
                    "INSERT INTO account_types (id, space_id, name, name_normalized, "
                    "behavior, is_system, is_active, created_by) "
                    "VALUES (:id, :s, :name, :n, 'loan', true, true, :by)"
                ),
                {
                    "id": uuid.uuid4(),
                    "s": space_id,
                    "name": name,
                    "n": normalize_name(name),
                    "by": created_by,
                },
            )
            return


def _ensure_gifts_category(bind: sa.Connection, space_id: uuid.UUID, created_by: uuid.UUID) -> None:
    normalized = normalize_name(GIFTS_CATEGORY)
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM categories WHERE space_id = :s AND kind = 'income' "
            "AND name_normalized = :n"
        ),
        {"s": space_id, "n": normalized},
    ).first()
    if exists is None:
        bind.execute(
            sa.text(
                "INSERT INTO categories (id, space_id, name, name_normalized, kind, "
                "is_system, is_active, created_by) "
                "VALUES (:id, :s, :name, :n, 'income', false, true, :by)"
            ),
            {
                "id": uuid.uuid4(),
                "s": space_id,
                "name": GIFTS_CATEGORY,
                "n": normalized,
                "by": created_by,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("La migración 0018 solo corre en Postgres (GLO-07)")

    op.drop_constraint("ck_account_type_behavior", "account_types", type_="check")
    op.create_check_constraint(
        "ck_account_type_behavior",
        "account_types",
        "behavior IN ('credit', 'debit', 'prepaid', 'cash', 'savings', 'loan')",
    )

    for space_id, created_by in bind.execute(sa.text("SELECT id, created_by FROM spaces")).all():
        _ensure_loan_type(bind, space_id, created_by)
        _ensure_gifts_category(bind, space_id, created_by)


def downgrade() -> None:
    raise NotImplementedError(
        "0018 no es reversible: restaura el respaldo previo (scripts/local/backup.sh, GLO-08)"
    )
