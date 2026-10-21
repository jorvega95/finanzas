"""Subscriptions module: rule kinds, trials, cancellation, foreign-currency
prices, variable bills and their reminders (REC-06b..REC-13, REM-08).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

OLD_FREQUENCIES = "frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly', 'yearly')"
NEW_FREQUENCIES = (
    "frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly', 'bimonthly', 'yearly')"
)
OLD_KINDS = "kind IN ('card_due', 'budget_alert', 'commitment_due', 'custom')"
NEW_KINDS = (
    "kind IN ('card_due', 'budget_alert', 'commitment_due', 'subscription_charge', "
    "'trial_ending', 'bill_due', 'custom')"
)


def upgrade() -> None:
    # REC-07/09/10/12 on recurring_rules.
    op.add_column(
        "recurring_rules",
        sa.Column("kind", sa.String(12), nullable=False, server_default="generic"),
    )
    op.add_column("recurring_rules", sa.Column("canceled_at", sa.Date()))
    op.add_column(
        "recurring_rules",
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "recurring_rules",
        sa.Column("reminder_days", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("recurring_rules", sa.Column("cancel_url", sa.String(500)))
    op.add_column("recurring_rules", sa.Column("notes", sa.Text()))
    op.create_check_constraint(
        "ck_rule_kind", "recurring_rules", "kind IN ('generic', 'subscription', 'bill')"
    )
    # REC-11: bills may omit the amount.
    op.alter_column("recurring_rules", "amount", existing_type=sa.Numeric(14, 2), nullable=True)
    op.drop_constraint("ck_rule_amount_positive", "recurring_rules", type_="check")
    op.create_check_constraint(
        "ck_rule_amount_positive", "recurring_rules", "amount IS NULL OR amount > 0"
    )
    op.create_check_constraint(
        "ck_rule_amount_required", "recurring_rules", "kind = 'bill' OR amount IS NOT NULL"
    )
    # REC-06b.
    op.drop_constraint("ck_rule_frequency", "recurring_rules", type_="check")
    op.create_check_constraint("ck_rule_frequency", "recurring_rules", NEW_FREQUENCIES)

    # REC-08: informational original price on generated transactions.
    op.add_column("transactions", sa.Column("original_amount", sa.Numeric(14, 2)))
    op.add_column("transactions", sa.Column("original_currency", sa.String(3)))

    # REC-12 / REM-08 on reminders.
    op.alter_column(
        "reminders", "kind", type_=sa.String(20), existing_type=sa.String(15), nullable=False
    )
    op.drop_constraint("ck_reminder_kind", "reminders", type_="check")
    op.create_check_constraint("ck_reminder_kind", "reminders", NEW_KINDS)
    op.drop_constraint("ck_reminder_channel", "reminders", type_="check")
    op.create_check_constraint(
        "ck_reminder_channel", "reminders", "channel IN ('in_app', 'email', 'desktop')"
    )
    op.add_column("reminders", sa.Column("recurring_rule_id", sa.Uuid()))
    op.create_foreign_key(
        "reminders_recurring_rule_id_fkey",
        "reminders",
        "recurring_rules",
        ["recurring_rule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_reminders_recurring_rule_id", "reminders", ["recurring_rule_id"])
    op.add_column("reminders", sa.Column("ref_date", sa.Date()))


def downgrade() -> None:
    op.drop_column("reminders", "ref_date")
    op.drop_index("ix_reminders_recurring_rule_id", table_name="reminders")
    op.drop_constraint("reminders_recurring_rule_id_fkey", "reminders", type_="foreignkey")
    op.drop_column("reminders", "recurring_rule_id")
    op.execute(
        "DELETE FROM reminders WHERE channel = 'desktop' "
        "OR kind IN ('subscription_charge', 'trial_ending', 'bill_due')"
    )
    op.drop_constraint("ck_reminder_channel", "reminders", type_="check")
    op.create_check_constraint("ck_reminder_channel", "reminders", "channel IN ('in_app', 'email')")
    op.drop_constraint("ck_reminder_kind", "reminders", type_="check")
    op.create_check_constraint("ck_reminder_kind", "reminders", OLD_KINDS)
    op.alter_column(
        "reminders", "kind", type_=sa.String(15), existing_type=sa.String(20), nullable=False
    )

    op.drop_column("transactions", "original_currency")
    op.drop_column("transactions", "original_amount")

    op.execute("DELETE FROM recurring_rules WHERE kind = 'bill' AND amount IS NULL")
    op.execute("UPDATE recurring_rules SET frequency = 'monthly' WHERE frequency = 'bimonthly'")
    op.drop_constraint("ck_rule_frequency", "recurring_rules", type_="check")
    op.create_check_constraint("ck_rule_frequency", "recurring_rules", OLD_FREQUENCIES)
    op.drop_constraint("ck_rule_amount_required", "recurring_rules", type_="check")
    op.drop_constraint("ck_rule_amount_positive", "recurring_rules", type_="check")
    op.create_check_constraint("ck_rule_amount_positive", "recurring_rules", "amount > 0")
    op.alter_column("recurring_rules", "amount", existing_type=sa.Numeric(14, 2), nullable=False)
    op.drop_constraint("ck_rule_kind", "recurring_rules", type_="check")
    for column in ("notes", "cancel_url", "reminder_days", "is_trial", "canceled_at", "kind"):
        op.drop_column("recurring_rules", column)
