"""Pydantic schemas for invoicing (FAC-01..FAC-06, FAC-10/11/14). GLO-01:
money travels as strings."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models.billing import FilingKind
from app.schemas.transactions import Money, MoneyNonNeg, MoneyOut

# FAC-06: Banxico "para solventar obligaciones", 4 decimals.
FiscalRate = Annotated[
    Decimal,
    Field(gt=0, max_digits=10, decimal_places=4),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]
SatUrl = Annotated[str, Field(max_length=500, pattern=r"^(https://\S+)?$")]  # FAC-14
CFDI_UUID_PATTERN = r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"


class BillingSettingsIn(BaseModel):
    sat_invoice_url: SatUrl | None = None
    sat_filing_url: SatUrl | None = None
    sat_payment_url: SatUrl | None = None
    # FAC-12: 1-2 → 1, 3-4 → 2, 5-6 → 3, 7-8 → 4, 9-0 → 5 business days.
    rfc_extra_days: int | None = Field(default=None, ge=0, le=5)


class BillingSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sat_invoice_url: str | None = None
    sat_filing_url: str | None = None
    sat_payment_url: str | None = None
    rfc_extra_days: int = 0


class BillingClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    tax_id: str | None = Field(default=None, max_length=13)
    foreign_tax_id: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, max_length=60)
    fiscal_regime: str | None = Field(default=None, max_length=60)
    cfdi_use: str | None = Field(default=None, max_length=60)
    product_code: str | None = Field(default=None, max_length=60)
    unit_code: str | None = Field(default=None, max_length=60)
    postal_code: str | None = Field(default=None, max_length=10)
    concept_template: str | None = Field(default=None, max_length=1000)


class BillingClientUpdate(BillingClientIn):
    name: str | None = Field(default=None, min_length=1, max_length=120)  # type: ignore[assignment]
    is_active: bool | None = None


class BillingClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    tax_id: str | None
    foreign_tax_id: str | None
    country: str | None
    fiscal_regime: str | None
    cfdi_use: str | None
    product_code: str | None
    unit_code: str | None
    postal_code: str | None
    concept_template: str | None
    is_active: bool


class StoredFileOut(BaseModel):
    """FAC-10: metadata only; the content is served by GET /billing/files/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str
    mime: str
    size: int
    created_at: dt.datetime


class InvoiceIn(BaseModel):
    """FAC-03: the CFDI of a payment."""

    cfdi_uuid: str | None = Field(default=None, pattern=CFDI_UUID_PATTERN)
    issue_date: dt.date
    total: Money
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    fx_rate: FiscalRate | None = None
    file_id: uuid.UUID | None = None
    notes: str | None = None


class InvoiceOut(BaseModel):
    id: uuid.UUID
    cfdi_uuid: str | None
    issue_date: dt.date
    total: MoneyOut
    currency: str
    fx_rate: FiscalRate | None
    file: StoredFileOut | None
    notes: str | None


class OldPaymentCreate(BaseModel):
    """FAC-01b: a payment no longer in the wallet; may come already invoiced."""

    client_id: uuid.UUID
    payment_date: dt.date
    amount: Money
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    fiscal_fx_rate: FiscalRate | None = None
    work_period_start: dt.date | None = None
    work_period_end: dt.date | None = None
    description: str = Field(default="", max_length=200)
    notes: str | None = None
    capture_file_id: uuid.UUID | None = None
    invoice: InvoiceIn | None = None


class PaymentUpdate(BaseModel):
    """Only the fields sent are applied. Date/amount/currency only for an old
    payment (FAC-02: an income's payment follows its transaction)."""

    client_id: uuid.UUID | None = None
    payment_date: dt.date | None = None
    amount: Money | None = None
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    fiscal_fx_rate: FiscalRate | None = None
    work_period_start: dt.date | None = None
    work_period_end: dt.date | None = None
    description: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    is_excluded: bool | None = None
    capture_file_id: uuid.UUID | None = None


class PaymentOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    transaction_id: uuid.UUID | None
    account_id: uuid.UUID | None  # of its income, if any
    payment_date: dt.date
    period: dt.date  # FAC-02: first day of the fiscal month
    amount: MoneyOut
    currency: str
    fiscal_fx_rate: FiscalRate | None
    mxn: MoneyOut | None  # FAC-06; None while the rate is missing
    work_period_start: dt.date | None
    work_period_end: dt.date | None
    description: str
    notes: str | None
    is_excluded: bool
    status: str  # FAC-04: pending_invoice | invoiced | excluded
    invoice: InvoiceOut | None
    invoice_mismatch: bool
    capture_file: StoredFileOut | None


class BillingSummaryOut(BaseModel):
    counts: dict[str, int]
    pending_amounts: dict[str, MoneyOut]


class InvoiceSheetOut(BaseModel):
    """FAC-11: what to type in the SAT portal for one payment."""

    payment: PaymentOut
    client: BillingClientOut
    description: str
    missing: list[str]  # e.g. "work_period", "fiscal_fx_rate"
    sat_invoice_url: str | None


class InvoiceableAccountIn(BaseModel):
    """FAC-01: flag (or unflag with null) an invoiceable account."""

    client_id: uuid.UUID | None
    import_since: dt.date | None = None


class InvoiceableAccountOut(BaseModel):
    account_id: uuid.UUID
    client_id: uuid.UUID | None
    imported: int


# --- Declarations (FAC-06/07/08/12/13) --------------------------------------------------


class FilingPaymentIn(BaseModel):
    """FAC-12: payment of the capture line. FAC-13: with `account_id`, an
    "Impuestos" expense is created in that (MXN) account."""

    paid_date: dt.date
    paid_amount: Money
    receipt_file_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None


class FilingIn(BaseModel):
    period: dt.date  # any day of the fiscal month
    kind: FilingKind = FilingKind.normal
    filed_date: dt.date
    operation_number: str | None = Field(default=None, max_length=40)
    capture_line: str | None = Field(default=None, max_length=60)
    declared_income: MoneyNonNeg | None = None
    isr_amount: MoneyNonNeg = Decimal("0.00")
    iva_amount: MoneyNonNeg = Decimal("0.00")
    amount_due: MoneyNonNeg = Decimal("0.00")
    valid_until: dt.date | None = None
    ack_file_id: uuid.UUID | None = None
    notes: str | None = None
    payment: FilingPaymentIn | None = None  # an old period, already paid


class FilingUpdate(BaseModel):
    kind: FilingKind | None = None
    filed_date: dt.date | None = None
    operation_number: str | None = Field(default=None, max_length=40)
    capture_line: str | None = Field(default=None, max_length=60)
    declared_income: MoneyNonNeg | None = None
    isr_amount: MoneyNonNeg | None = None
    iva_amount: MoneyNonNeg | None = None
    amount_due: MoneyNonNeg | None = None
    valid_until: dt.date | None = None
    ack_file_id: uuid.UUID | None = None
    notes: str | None = None


class FilingOut(BaseModel):
    id: uuid.UUID
    period: dt.date
    kind: FilingKind
    filed_date: dt.date
    operation_number: str | None
    capture_line: str | None
    declared_income: MoneyOut | None
    isr_amount: MoneyOut
    iva_amount: MoneyOut
    amount_due: MoneyOut
    valid_until: dt.date | None
    ack_file: StoredFileOut | None
    paid_date: dt.date | None
    paid_amount: MoneyOut | None
    receipt_file: StoredFileOut | None
    expense_transaction_id: uuid.UUID | None
    notes: str | None


class PrefillItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: uuid.UUID
    payment_date: dt.date
    issue_date: dt.date
    mxn: MoneyOut | None


class PeriodOut(BaseModel):
    period: dt.date
    status: str  # open | to_declare | to_pay | paid
    is_overdue: bool
    deadline: dt.date  # FAC-12: day 17 (+ business days)
    payment_deadline: dt.date | None  # the acuse's "vigente hasta", if unpaid
    to_declare: MoneyOut  # FAC-06: whole pesos
    missing_rates: int
    pending_invoice: int
    isr_rate: MoneyOut  # FAC-07
    isr_estimate: MoneyOut
    sat_prefill: MoneyOut  # FAC-08
    prefill_unknown: int
    exclude_from_prefill: list[PrefillItemOut]
    add_to_prefill: list[PrefillItemOut]
    amount_due: MoneyOut
    payment_ids: list[uuid.UUID]
    filings: list[FilingOut]


class CfdiCheckOut(BaseModel):
    """FAC-15: what the uploaded CFDI says and what disagrees with its payment
    (codes: total, currency, fx_rate, issue_month, iva, receiver)."""

    uuid: str | None
    issue_date: dt.date | None
    total: MoneyOut | None
    currency: str | None
    fx_rate: MoneyOut | None
    issuer_rfc: str | None
    receiver_rfc: str | None
    receiver_name: str | None
    iva_rates: list[MoneyOut]
    warnings: list[str]
