"""Invoicing of freelance income (RESICO). Implements FAC-01..FAC-05,
FAC-10..FAC-14.

A payment (`invoiceable_payments`) is born from an income in an invoiceable
account (FAC-01a) or captured by hand as an old payment (FAC-01b). Its status
is computed from its invoice (FAC-04), never stored."""

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import AuditMixin, TimestampMixin


class BillingSettings(Base, TimestampMixin):
    """FAC-14: one row per space with the SAT portal URLs (https only)."""

    __tablename__ = "billing_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    sat_invoice_url: Mapped[str | None] = mapped_column(String(500))
    sat_filing_url: Mapped[str | None] = mapped_column(String(500))
    sat_payment_url: Mapped[str | None] = mapped_column(String(500))
    # FAC-12: extra business days granted by the sixth digit of the RFC (0-5).
    rfc_extra_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class BillingClient(Base, AuditMixin):
    """FAC-11: fiscal data of who pays (the receptor of the CFDI) and the
    concept template used to build the invoice description."""

    __tablename__ = "billing_clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(13))  # RFC (XEXX010101000 abroad)
    foreign_tax_id: Mapped[str | None] = mapped_column(String(40))  # e.g. EIN
    country: Mapped[str | None] = mapped_column(String(60))
    fiscal_regime: Mapped[str | None] = mapped_column(String(60))  # e.g. "616"
    cfdi_use: Mapped[str | None] = mapped_column(String(60))  # e.g. "S01"
    product_code: Mapped[str | None] = mapped_column(String(60))  # e.g. "81112000"
    unit_code: Mapped[str | None] = mapped_column(String(60))  # e.g. "E48"
    postal_code: Mapped[str | None] = mapped_column(String(10))
    # Placeholders {periodo} and {fecha_pago} (FAC-11).
    concept_template: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StoredFile(Base, AuditMixin):
    """FAC-10: metadata of a file kept on disk under FILES_DIR. The original
    name is metadata only; `storage_path` is generated and relative."""

    __tablename__ = "stored_files"
    __table_args__ = (CheckConstraint("size > 0", name="ck_stored_file_size_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(60), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)


class InvoiceablePayment(Base, AuditMixin):
    """FAC-01: one freelance payment to invoice. FAC-02: its fiscal period is
    the month of `payment_date` (computed, never stored)."""

    __tablename__ = "invoiceable_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_invoiceable_payment_amount_positive"),
        CheckConstraint(
            "fiscal_fx_rate IS NULL OR fiscal_fx_rate > 0", name="ck_invoiceable_payment_fx"
        ),
        CheckConstraint(
            "work_period_start IS NULL OR work_period_end IS NULL "
            "OR work_period_start <= work_period_end",
            name="ck_invoiceable_payment_work_period",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("billing_clients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # FAC-01a: 1:1 with its income; NULL for an old payment (FAC-01b). FAC-05:
    # the transaction service removes or protects it before deleting (NO ACTION,
    # not RESTRICT, so a space delete can cascade both rows in one statement).
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id"), unique=True
    )
    payment_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # FAC-06: Banxico "para solventar obligaciones" of payment_date, 4 decimals.
    # Independent of transactions.fx_rate_to_base (FX-03).
    fiscal_fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    work_period_start: Mapped[dt.date | None] = mapped_column(Date)  # FAC-11
    work_period_end: Mapped[dt.date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text)
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # FAC-04
    # Screenshot of the wallet movement (guide, part 1).
    capture_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stored_files.id", ondelete="SET NULL")
    )


class Invoice(Base, AuditMixin):
    """FAC-03: the CFDI of a payment (1:1)."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("space_id", "cfdi_uuid", name="uq_invoice_cfdi_uuid"),
        CheckConstraint("total > 0", name="ck_invoice_total_positive"),
        CheckConstraint("fx_rate IS NULL OR fx_rate > 0", name="ck_invoice_fx_rate_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoiceable_payments.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    cfdi_uuid: Mapped[str | None] = mapped_column(String(36))  # folio fiscal
    issue_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stored_files.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class FilingKind(enum.StrEnum):
    normal = "normal"
    complementary = "complementary"


class TaxFiling(Base, AuditMixin):
    """FAC-12: a monthly provisional declaration (acuse) and its payment.
    [period_start, period_end] is the fiscal month (FAC-02); both are stored
    so payments can be matched by date range in portable SQL."""

    __tablename__ = "tax_filings"
    __table_args__ = (
        CheckConstraint("period_start <= period_end", name="ck_tax_filing_period"),
        CheckConstraint(
            "isr_amount >= 0 AND iva_amount >= 0 AND amount_due >= 0",
            name="ck_tax_filing_amounts",
        ),
        CheckConstraint("paid_amount IS NULL OR paid_amount > 0", name="ck_tax_filing_paid"),
        CheckConstraint(
            "(paid_date IS NULL) = (paid_amount IS NULL)", name="ck_tax_filing_payment_pair"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    kind: Mapped[FilingKind] = mapped_column(
        Enum(FilingKind, name="filing_kind", native_enum=False, length=15),
        nullable=False,
        default=FilingKind.normal,
    )
    filed_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    operation_number: Mapped[str | None] = mapped_column(String(40))
    capture_line: Mapped[str | None] = mapped_column(String(60))
    # Pesos (FAC-06): what was declared and what it produced.
    declared_income: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    isr_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    iva_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    amount_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    valid_until: Mapped[dt.date | None] = mapped_column(Date)  # "Vigente hasta"
    ack_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stored_files.id", ondelete="SET NULL")
    )
    # Payment of the capture line.
    paid_date: Mapped[dt.date | None] = mapped_column(Date)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    receipt_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stored_files.id", ondelete="SET NULL")
    )
    # FAC-13: the "Impuestos" expense created with the payment (NO ACTION; the
    # transaction service unlinks it before deleting it).
    expense_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id")
    )
    notes: Mapped[str | None] = mapped_column(Text)
