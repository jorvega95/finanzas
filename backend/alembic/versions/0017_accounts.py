"""Accounts: cards become accounts and payment methods are merged into them.

Implements TAR-01..TAR-10, CAT-07 (derogated), CAT-08, TXN-13/14:

- `cards` → `accounts` (`alias` → `name`, unique `name_normalized`; bank,
  network and last4 become optional), `card_types` → `account_types` with the
  new `cash` and `savings` behaviors, `card_layouts` → `account_layouts`,
  `card_statements` → `statements`; every `credit_card_id` → `account_id`.
- Each payment method without a card becomes an account (the "Efectivo"
  method ⇒ a `cash` account); transactions and recurring rules then point at
  accounts (`account_id`, `account_to_id`) and `payment_methods` is dropped.
- Transactions gain `amount_to` (TXN-13) and `fee_for_id` (TXN-14).

Postgres only (GLO-07). Downgrade is not supported: restore the backup taken
before upgrading (GLO-08, scripts/local/backup.sh).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-19
"""

import uuid

import sqlalchemy as sa

from alembic import op
from app.core.text import normalize_name

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

# CAT-08: account types every space must have after this migration.
NEW_ACCOUNT_TYPES = [
    ("Billetera digital", "debit"),
    ("Efectivo", "cash"),
    ("Ahorro", "savings"),
]
# Payment method type → (preferred account type name, behavior) for the
# accounts created from methods that had no card.
METHOD_TO_TYPE = {
    "cash": ("Efectivo", "cash"),
    "debit": ("Débito", "debit"),
    "prepaid": ("Vales de despensa", "prepaid"),
    "transfer": ("Billetera digital", "debit"),
    "other": ("Billetera digital", "debit"),
}
# Constraint/index name fragments renamed so names match the new tables.
NAME_FRAGMENTS = [
    ("credit_cards_", "accounts_"),
    ("card_statements_", "statements_"),
    ("card_layouts_", "account_layouts_"),
    ("card_types_", "account_types_"),
    ("cards_", "accounts_"),
    ("credit_card_id", "account_id"),
    ("card_type_id", "account_type_id"),
    ("card_ids", "account_ids"),
    ("alias", "name"),
]
RENAMED_TABLES = ["accounts", "account_types", "account_layouts", "statements", "installment_plans"]


def _rename_names(bind: sa.Connection) -> None:
    """Rename leftover constraint and index names (e.g. credit_cards_pkey)."""
    for table in RENAMED_TABLES:
        constraints = bind.execute(
            sa.text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"),
            {"t": table},
        ).scalars()
        constraint_names = set()
        for name in list(constraints):
            constraint_names.add(name)
            new = name
            for old, rep in NAME_FRAGMENTS:
                new = new.replace(old, rep)
            if new != name:
                op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{name}" TO "{new}"')
        indexes = bind.execute(
            sa.text("SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": table}
        ).scalars()
        for name in list(indexes):
            if name in constraint_names:
                continue  # renamed together with its constraint
            new = name
            for old, rep in NAME_FRAGMENTS:
                new = new.replace(old, rep)
            if new != name:
                op.execute(f'ALTER INDEX "{name}" RENAME TO "{new}"')


def _ensure_account_types(bind: sa.Connection) -> None:
    spaces = bind.execute(sa.text("SELECT id, created_by FROM spaces")).all()
    for space_id, created_by in spaces:
        for name, behavior in NEW_ACCOUNT_TYPES:
            normalized = normalize_name(name)
            exists = bind.execute(
                sa.text("SELECT 1 FROM account_types WHERE space_id = :s AND name_normalized = :n"),
                {"s": space_id, "n": normalized},
            ).first()
            if exists is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO account_types (id, space_id, name, name_normalized, "
                        "behavior, is_system, is_active, created_by) "
                        "VALUES (:id, :s, :name, :n, :b, true, true, :by)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "s": space_id,
                        "name": name,
                        "n": normalized,
                        "b": behavior,
                        "by": created_by,
                    },
                )


def _type_for(bind: sa.Connection, space_id: uuid.UUID, name: str, behavior: str) -> uuid.UUID:
    """The space's account type with that name, else any with that behavior."""
    row = bind.execute(
        sa.text(
            "SELECT id FROM account_types WHERE space_id = :s AND behavior = :b "
            "ORDER BY (name_normalized = :n) DESC, created_at LIMIT 1"
        ),
        {"s": space_id, "b": behavior, "n": normalize_name(name)},
    ).scalar_one()
    return uuid.UUID(str(row))


def _insert_account(
    bind: sa.Connection,
    *,
    space_id: uuid.UUID,
    type_id: uuid.UUID,
    name: str,
    currency: str,
    is_active: bool,
    created_by: uuid.UUID,
) -> uuid.UUID:
    account_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO accounts (id, space_id, account_type_id, name, name_normalized, "
            "currency, initial_balance, allow_overdraft, reminder_days, is_active, created_by) "
            "VALUES (:id, :s, :t, :name, :n, :cur, 0, true, CAST('[]' AS json), :active, :by)"
        ),
        {
            "id": account_id,
            "s": space_id,
            "t": type_id,
            "name": name,
            "n": normalize_name(name),
            "cur": currency,
            "active": is_active,
            "by": created_by,
        },
    )
    return account_id


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("La migración 0017 solo corre en Postgres (GLO-07)")

    # --- Account types (CAT-08) ------------------------------------------------
    op.rename_table("card_types", "account_types")
    op.drop_constraint("ck_card_type_behavior", "account_types", type_="check")
    op.create_check_constraint(
        "ck_account_type_behavior",
        "account_types",
        "behavior IN ('credit', 'debit', 'prepaid', 'cash', 'savings')",
    )
    op.execute(
        "ALTER TABLE account_types RENAME CONSTRAINT uq_card_type_name TO uq_account_type_name"
    )
    _ensure_account_types(bind)

    # --- Accounts (TAR-01/02) --------------------------------------------------
    op.rename_table("cards", "accounts")
    op.alter_column("accounts", "card_type_id", new_column_name="account_type_id")
    op.alter_column("accounts", "alias", new_column_name="name")
    for column in ("bank", "network", "last4"):
        op.alter_column("accounts", column, nullable=True)
    op.execute(
        "ALTER TABLE accounts RENAME CONSTRAINT ck_card_payment_rule TO ck_account_payment_rule"
    )
    op.execute(
        "ALTER TABLE accounts RENAME CONSTRAINT ck_card_statement_day TO ck_account_statement_day"
    )
    op.execute(
        "ALTER TABLE accounts RENAME CONSTRAINT fk_cards_card_type TO accounts_account_type_id_fkey"
    )
    op.add_column("accounts", sa.Column("name_normalized", sa.String(60)))
    for account_id, name in bind.execute(sa.text("SELECT id, name FROM accounts")).all():
        bind.execute(
            sa.text("UPDATE accounts SET name_normalized = :n WHERE id = :id"),
            {"n": normalize_name(name), "id": account_id},
        )

    # --- Layouts and statements (TAR-07, TDC-03) -------------------------------
    op.rename_table("card_layouts", "account_layouts")
    op.alter_column("account_layouts", "card_ids", new_column_name="account_ids")
    op.execute(
        "ALTER TABLE account_layouts RENAME CONSTRAINT uq_card_layout_user_space "
        "TO uq_account_layout_user_space"
    )
    op.rename_table("card_statements", "statements")
    op.alter_column("statements", "credit_card_id", new_column_name="account_id")
    op.execute("ALTER INDEX ix_card_statements_card RENAME TO ix_statements_account_id")
    op.alter_column("installment_plans", "credit_card_id", new_column_name="account_id")

    # --- Payment methods → accounts (TAR-03, CAT-07 derogated) -----------------
    op.add_column("payment_methods", sa.Column("account_id", sa.Uuid()))
    op.execute("UPDATE payment_methods SET account_id = card_id WHERE card_id IS NOT NULL")
    loose = bind.execute(
        sa.text(
            "SELECT pm.id, pm.space_id, pm.name, pm.type, pm.is_active, pm.created_by, "
            "s.base_currency FROM payment_methods pm JOIN spaces s ON s.id = pm.space_id "
            "WHERE pm.card_id IS NULL"
        )
    ).all()
    for method_id, space_id, name, method_type, is_active, created_by, currency in loose:
        type_name, behavior = METHOD_TO_TYPE[method_type]
        account_id = _insert_account(
            bind,
            space_id=space_id,
            type_id=_type_for(bind, space_id, type_name, behavior),
            name=name,
            currency=currency,
            is_active=is_active,
            created_by=created_by,
        )
        bind.execute(
            sa.text("UPDATE payment_methods SET account_id = :a WHERE id = :m"),
            {"a": account_id, "m": method_id},
        )
    # CAT-02: every space ends up with a cash account.
    without_cash = bind.execute(
        sa.text(
            "SELECT s.id, s.base_currency, s.created_by FROM spaces s WHERE NOT EXISTS ("
            "SELECT 1 FROM accounts a JOIN account_types t ON t.id = a.account_type_id "
            "WHERE a.space_id = s.id AND t.behavior = 'cash')"
        )
    ).all()
    for space_id, currency, created_by in without_cash:
        taken = bind.execute(
            sa.text("SELECT 1 FROM accounts WHERE space_id = :s AND name_normalized = 'efectivo'"),
            {"s": space_id},
        ).first()
        _insert_account(
            bind,
            space_id=space_id,
            type_id=_type_for(bind, space_id, "Efectivo", "cash"),
            name="Efectivo (cuenta)" if taken else "Efectivo",
            currency=currency,
            is_active=True,
            created_by=created_by,
        )
    # TAR-09: cash always allows overdraft.
    op.execute(
        "UPDATE accounts SET allow_overdraft = true FROM account_types t "
        "WHERE t.id = accounts.account_type_id AND t.behavior = 'cash'"
    )
    op.alter_column("accounts", "name_normalized", nullable=False)
    op.create_unique_constraint("uq_account_name", "accounts", ["space_id", "name_normalized"])

    # --- Transactions and recurring rules point at accounts --------------------
    op.add_column("transactions", sa.Column("account_id", sa.Uuid()))
    op.add_column("transactions", sa.Column("account_to_id", sa.Uuid()))
    op.execute(
        "UPDATE transactions SET account_id = pm.account_id FROM payment_methods pm "
        "WHERE pm.id = transactions.payment_method_id"
    )
    op.execute(
        "UPDATE transactions SET account_to_id = pm.account_id FROM payment_methods pm "
        "WHERE pm.id = transactions.payment_method_to_id"
    )
    op.add_column("recurring_rules", sa.Column("account_id", sa.Uuid()))
    op.execute(
        "UPDATE recurring_rules SET account_id = pm.account_id FROM payment_methods pm "
        "WHERE pm.id = recurring_rules.payment_method_id"
    )
    op.alter_column("transactions", "account_id", nullable=False)
    op.alter_column("recurring_rules", "account_id", nullable=False)
    op.create_foreign_key(
        "transactions_account_id_fkey",
        "transactions",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "transactions_account_to_id_fkey",
        "transactions",
        "accounts",
        ["account_to_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "recurring_rules_account_id_fkey",
        "recurring_rules",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_transactions_account_id", "transactions", ["account_id"])
    op.create_index("ix_transactions_account_to_id", "transactions", ["account_to_id"])

    # TXN-13/14: received amount of cross-currency transfers and transfer fees.
    op.add_column("transactions", sa.Column("amount_to", sa.Numeric(14, 2)))
    op.create_check_constraint(
        "ck_txn_amount_to_positive", "transactions", "amount_to IS NULL OR amount_to > 0"
    )
    op.add_column("transactions", sa.Column("fee_for_id", sa.Uuid()))
    op.create_foreign_key(
        "transactions_fee_for_id_fkey",
        "transactions",
        "transactions",
        ["fee_for_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_transactions_fee_for_id", "transactions", ["fee_for_id"])

    op.drop_column("transactions", "payment_method_id")
    op.drop_column("transactions", "payment_method_to_id")
    op.drop_column("transactions", "card_id")
    op.drop_column("recurring_rules", "payment_method_id")
    op.drop_column("accounts", "payment_method_id")
    op.drop_table("payment_methods")

    _rename_names(bind)


def downgrade() -> None:
    raise NotImplementedError(
        "0017 no es reversible: restaura el respaldo previo (scripts/local/backup.sh, GLO-08)"
    )
