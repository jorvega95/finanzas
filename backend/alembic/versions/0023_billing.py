"""Invoicing and RESICO declarations of freelance income (FAC-01..FAC-14).

- New `billing_settings`, `billing_clients`, `stored_files`,
  `invoiceable_payments`, `invoices` and `tax_filings` tables.
- `accounts.invoice_client_id` (invoiceable account, FAC-01).
- Reminder kinds `invoice_pending` and `tax_filing_due` (FAC-09).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "kind IN ('card_due', 'budget_alert', 'commitment_due', 'subscription_charge', "
    "'trial_ending', 'bill_due', 'custom')"
)
NEW_KINDS = (
    "kind IN ('card_due', 'budget_alert', 'commitment_due', 'subscription_charge', "
    "'trial_ending', 'bill_due', 'invoice_pending', 'tax_filing_due', 'custom')"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _space_fk() -> sa.Column:
    return sa.Column(
        "space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )


def _created_by() -> sa.Column:
    return sa.Column("created_by", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "billing_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id",
            sa.Uuid(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("sat_invoice_url", sa.String(500)),
        sa.Column("sat_filing_url", sa.String(500)),
        sa.Column("sat_payment_url", sa.String(500)),
        sa.Column("rfc_extra_days", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )

    op.create_table(
        "billing_clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _space_fk(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("tax_id", sa.String(13)),
        sa.Column("foreign_tax_id", sa.String(40)),
        sa.Column("country", sa.String(60)),
        sa.Column("fiscal_regime", sa.String(60)),
        sa.Column("cfdi_use", sa.String(60)),
        sa.Column("product_code", sa.String(60)),
        sa.Column("unit_code", sa.String(60)),
        sa.Column("postal_code", sa.String(10)),
        sa.Column("concept_template", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _created_by(),
        *_timestamps(),
    )
    op.create_index("ix_billing_clients_space_id", "billing_clients", ["space_id"])

    op.create_table(
        "stored_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _space_fk(),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(60), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        _created_by(),
        *_timestamps(),
        sa.CheckConstraint("size > 0", name="ck_stored_file_size_positive"),
    )
    op.create_index("ix_stored_files_space_id", "stored_files", ["space_id"])

    op.create_table(
        "invoiceable_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _space_fk(),
        sa.Column(
            "client_id",
            sa.Uuid(),
            sa.ForeignKey("billing_clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("transactions.id"),
            unique=True,
        ),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("fiscal_fx_rate", sa.Numeric(10, 4)),
        sa.Column("work_period_start", sa.Date()),
        sa.Column("work_period_end", sa.Date()),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("notes", sa.Text()),
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "capture_file_id", sa.Uuid(), sa.ForeignKey("stored_files.id", ondelete="SET NULL")
        ),
        _created_by(),
        *_timestamps(),
        sa.CheckConstraint("amount > 0", name="ck_invoiceable_payment_amount_positive"),
        sa.CheckConstraint(
            "fiscal_fx_rate IS NULL OR fiscal_fx_rate > 0", name="ck_invoiceable_payment_fx"
        ),
        sa.CheckConstraint(
            "work_period_start IS NULL OR work_period_end IS NULL "
            "OR work_period_start <= work_period_end",
            name="ck_invoiceable_payment_work_period",
        ),
    )
    op.create_index("ix_invoiceable_payments_space_id", "invoiceable_payments", ["space_id"])
    op.create_index("ix_invoiceable_payments_client_id", "invoiceable_payments", ["client_id"])
    op.create_index(
        "ix_invoiceable_payments_payment_date", "invoiceable_payments", ["payment_date"]
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _space_fk(),
        sa.Column(
            "payment_id",
            sa.Uuid(),
            sa.ForeignKey("invoiceable_payments.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("cfdi_uuid", sa.String(36)),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("fx_rate", sa.Numeric(10, 4)),
        sa.Column("file_id", sa.Uuid(), sa.ForeignKey("stored_files.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        _created_by(),
        *_timestamps(),
        sa.UniqueConstraint("space_id", "cfdi_uuid", name="uq_invoice_cfdi_uuid"),
        sa.CheckConstraint("total > 0", name="ck_invoice_total_positive"),
        sa.CheckConstraint("fx_rate IS NULL OR fx_rate > 0", name="ck_invoice_fx_rate_positive"),
    )
    op.create_index("ix_invoices_space_id", "invoices", ["space_id"])
    op.create_index("ix_invoices_issue_date", "invoices", ["issue_date"])

    op.create_table(
        "tax_filings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _space_fk(),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(15), nullable=False, server_default="normal"),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("operation_number", sa.String(40)),
        sa.Column("capture_line", sa.String(60)),
        sa.Column("declared_income", sa.Numeric(14, 2)),
        sa.Column("isr_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("iva_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("amount_due", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("valid_until", sa.Date()),
        sa.Column("ack_file_id", sa.Uuid(), sa.ForeignKey("stored_files.id", ondelete="SET NULL")),
        sa.Column("paid_date", sa.Date()),
        sa.Column("paid_amount", sa.Numeric(14, 2)),
        sa.Column(
            "receipt_file_id", sa.Uuid(), sa.ForeignKey("stored_files.id", ondelete="SET NULL")
        ),
        sa.Column("expense_transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id")),
        sa.Column("notes", sa.Text()),
        _created_by(),
        *_timestamps(),
        sa.CheckConstraint("period_start <= period_end", name="ck_tax_filing_period"),
        sa.CheckConstraint(
            "isr_amount >= 0 AND iva_amount >= 0 AND amount_due >= 0",
            name="ck_tax_filing_amounts",
        ),
        sa.CheckConstraint("paid_amount IS NULL OR paid_amount > 0", name="ck_tax_filing_paid"),
        sa.CheckConstraint(
            "(paid_date IS NULL) = (paid_amount IS NULL)", name="ck_tax_filing_payment_pair"
        ),
        sa.CheckConstraint("kind IN ('normal', 'complementary')", name="ck_tax_filing_kind"),
    )
    op.create_index("ix_tax_filings_space_id", "tax_filings", ["space_id"])
    op.create_index("ix_tax_filings_period_start", "tax_filings", ["period_start"])

    op.add_column("accounts", sa.Column("invoice_client_id", sa.Uuid()))
    op.create_foreign_key(
        "accounts_invoice_client_id_fkey",
        "accounts",
        "billing_clients",
        ["invoice_client_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # FAC-09: invoicing and declaration reminders.
    op.drop_constraint("ck_reminder_kind", "reminders", type_="check")
    op.create_check_constraint("ck_reminder_kind", "reminders", NEW_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM reminders WHERE kind IN ('invoice_pending', 'tax_filing_due')")
    op.drop_constraint("ck_reminder_kind", "reminders", type_="check")
    op.create_check_constraint("ck_reminder_kind", "reminders", OLD_KINDS)
    op.drop_constraint("accounts_invoice_client_id_fkey", "accounts", type_="foreignkey")
    op.drop_column("accounts", "invoice_client_id")
    op.drop_table("tax_filings")
    op.drop_table("invoices")
    op.drop_table("invoiceable_payments")
    op.drop_table("stored_files")
    op.drop_table("billing_clients")
    op.drop_table("billing_settings")
