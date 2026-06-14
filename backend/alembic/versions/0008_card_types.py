"""Generalize cards: card types catalog, stored-value balance, net worth.

Implements CAT-08 and TAR-01..05: a `card_types` catalog with a system
`behavior` classifier (credit | debit | prepaid); renames `credit_cards`→`cards`
and `*.credit_card_id`→`*.card_id`; adds `card_type_id`, `initial_balance`,
`allow_overdraft`; backfills existing cards to a seeded "Crédito" type; relaxes
the credit-only CHECK constraints so non-credit cards omit those fields.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-13
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# CAT-08 seed: (name, name_normalized, behavior).
SEED_CARD_TYPES = [
    ("Crédito", "credito", "credit"),
    ("Débito", "debito", "debit"),
    ("Vales de despensa", "vales de despensa", "prepaid"),
    ("Tarjeta de regalo", "tarjeta de regalo", "prepaid"),
]


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # CAT-08: card types catalog.
    op.create_table(
        "card_types",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("name_normalized", sa.String(60), nullable=False),
        sa.Column("behavior", sa.String(10), nullable=False),
        sa.Column("icon", sa.String(40)),
        sa.Column("color", sa.String(20)),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "behavior IN ('credit', 'debit', 'prepaid')", name="ck_card_type_behavior"
        ),
        sa.UniqueConstraint("space_id", "name_normalized", name="uq_card_type_name"),
    )
    op.create_index("ix_card_types_space_id", "card_types", ["space_id"])

    # Rename the credit_cards table and the card-link columns (TAR-03).
    op.rename_table("credit_cards", "cards")
    op.alter_column("payment_methods", "credit_card_id", new_column_name="card_id")
    op.alter_column("transactions", "credit_card_id", new_column_name="card_id")

    # New card fields (TAR-01/TAR-05).
    op.add_column("cards", sa.Column("card_type_id", sa.Uuid()))
    op.add_column("cards", sa.Column("initial_balance", sa.Numeric(14, 2)))
    op.add_column(
        "cards",
        sa.Column("allow_overdraft", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_cards_card_type_id", "cards", ["card_type_id"])

    # Relax the credit-only CHECKs so non-credit cards may omit those fields.
    op.drop_constraint("ck_card_statement_day", "cards", type_="check")
    op.drop_constraint("ck_card_payment_rule", "cards", type_="check")
    op.create_check_constraint(
        "ck_card_statement_day",
        "cards",
        "statement_day_is_last OR statement_day IS NULL "
        "OR (statement_day >= 1 AND statement_day <= 28)",
    )
    op.create_check_constraint(
        "ck_card_payment_rule",
        "cards",
        "(payment_due_days IS NULL AND payment_day IS NULL AND NOT payment_day_is_last) "
        "OR ((payment_due_days IS NOT NULL) != "
        "(payment_day IS NOT NULL OR payment_day_is_last))",
    )

    if is_pg:
        # Seed card types per existing space (CAT-08).
        values = ", ".join(f"('{name}', '{norm}', '{beh}')" for name, norm, beh in SEED_CARD_TYPES)
        op.execute(
            f"""
            INSERT INTO card_types
                (id, space_id, name, name_normalized, behavior, is_system, is_active, created_by)
            SELECT gen_random_uuid(), s.id, v.name, v.norm, v.behavior, true, true, s.created_by
            FROM spaces s
            CROSS JOIN (VALUES {values}) AS v(name, norm, behavior);
            """
        )
        # Backfill existing cards to their space's "Crédito" type.
        op.execute(
            """
            UPDATE cards
            SET card_type_id = (
                SELECT ct.id FROM card_types ct
                WHERE ct.space_id = cards.space_id AND ct.behavior = 'credit'
                LIMIT 1
            )
            WHERE card_type_id IS NULL;
            """
        )
        op.alter_column("cards", "card_type_id", nullable=False)
        op.create_foreign_key(
            "fk_cards_card_type",
            "cards",
            "card_types",
            ["card_type_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        # RLS (GLO-05): card_types + rename the renamed table's policy.
        op.execute("ALTER TABLE public.card_types ENABLE ROW LEVEL SECURITY;")
        op.execute(
            """
            CREATE POLICY card_types_space_isolation ON public.card_types
            USING (public.is_space_member(space_id));
            """
        )
        op.execute(
            "ALTER POLICY credit_cards_space_isolation ON public.cards "
            "RENAME TO cards_space_isolation;"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute(
            "ALTER POLICY cards_space_isolation ON public.cards "
            "RENAME TO credit_cards_space_isolation;"
        )
        op.execute("DROP POLICY IF EXISTS card_types_space_isolation ON public.card_types;")
        op.drop_constraint("fk_cards_card_type", "cards", type_="foreignkey")

    op.drop_constraint("ck_card_payment_rule", "cards", type_="check")
    op.drop_constraint("ck_card_statement_day", "cards", type_="check")
    op.create_check_constraint(
        "ck_card_statement_day",
        "cards",
        "statement_day_is_last OR (statement_day >= 1 AND statement_day <= 28)",
    )
    op.create_check_constraint(
        "ck_card_payment_rule",
        "cards",
        "(payment_due_days IS NOT NULL) != (payment_day IS NOT NULL OR payment_day_is_last)",
    )

    op.drop_index("ix_cards_card_type_id", table_name="cards")
    op.drop_column("cards", "allow_overdraft")
    op.drop_column("cards", "initial_balance")
    op.drop_column("cards", "card_type_id")

    op.alter_column("transactions", "card_id", new_column_name="credit_card_id")
    op.alter_column("payment_methods", "card_id", new_column_name="credit_card_id")
    op.rename_table("cards", "credit_cards")

    op.drop_index("ix_card_types_space_id", table_name="card_types")
    op.drop_table("card_types")
