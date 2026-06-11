"""Space invites + Row-Level Security (Fase 5).

Implements ESP-04 (invites) and the RLS second defense layer (GLO-05):
FastAPI filters first; these policies guard direct Postgres/Supabase access.
RLS only applies on PostgreSQL (tests run on SQLite with create_all).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# Toda tabla de dominio con space_id (GLO-05).
SPACE_TABLES = [
    "categories",
    "payment_methods",
    "transactions",
    "recurring_rules",
    "credit_cards",
    "card_statements",
    "installment_plans",
    "reminders",
    "budgets",
    "investment_accounts",
    "portfolio_snapshots",
    "net_worth_snapshots",
    "space_invites",
]


def upgrade() -> None:
    op.create_table(
        "space_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_invite_role"),
    )
    op.create_index("ix_space_invites_space_id", "space_invites", ["space_id"])

    # --- RLS (solo Postgres/Supabase) -------------------------------------
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.is_space_member(target_space uuid)
        RETURNS boolean
        LANGUAGE sql SECURITY DEFINER STABLE AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.space_members
                WHERE space_id = target_space AND user_id = auth.uid()
            );
        $$;
        """
    )
    for table in SPACE_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_space_isolation ON public.{table}
            USING (public.is_space_member(space_id));
            """
        )
    # Tablas sin space_id directo.
    op.execute("ALTER TABLE public.spaces ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY spaces_member_only ON public.spaces
        USING (public.is_space_member(id));
        """
    )
    op.execute("ALTER TABLE public.space_members ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY space_members_self ON public.space_members
        USING (user_id = auth.uid() OR public.is_space_member(space_id));
        """
    )
    op.execute("ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY profiles_self ON public.profiles
        USING (id = auth.uid());
        """
    )
    op.execute("ALTER TABLE public.installments ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY installments_via_plan ON public.installments
        USING (EXISTS (
            SELECT 1 FROM public.installment_plans p
            WHERE p.id = plan_id AND public.is_space_member(p.space_id)
        ));
        """
    )
    op.execute("ALTER TABLE public.holdings ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY holdings_via_account ON public.holdings
        USING (EXISTS (
            SELECT 1 FROM public.investment_accounts a
            WHERE a.id = account_id AND public.is_space_member(a.space_id)
        ));
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in SPACE_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_space_isolation ON public.{table};")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS spaces_member_only ON public.spaces;")
        op.execute("DROP POLICY IF EXISTS space_members_self ON public.space_members;")
        op.execute("DROP POLICY IF EXISTS profiles_self ON public.profiles;")
        op.execute("DROP POLICY IF EXISTS installments_via_plan ON public.installments;")
        op.execute("DROP POLICY IF EXISTS holdings_via_account ON public.holdings;")
        op.execute("DROP FUNCTION IF EXISTS public.is_space_member(uuid);")
    op.drop_table("space_invites")
