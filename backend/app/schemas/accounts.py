"""Pydantic schemas for accounts, statements, MSI and reminders (Fase 2)."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.accounts import CutoffDayPolicy, StatementStatus
from app.models.catalogs import AccountBehavior
from app.models.msi import InstallmentStatus, PlanStatus
from app.schemas.transactions import Money, MoneyNonNeg, MoneyOut, MoneySigned

# TAR-08: account design. Hex base color and a front-image data URL (never the PAN:
# TDC-01 — the UI warns; the backend only checks format and size).
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
IMAGE_PATTERN = r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}$"
IMAGE_MAX_LENGTH = 1_000_000


class AccountCreate(BaseModel):
    account_type_id: uuid.UUID  # CAT-08/TAR-01
    name: str = Field(min_length=1, max_length=60)
    # TAR-02: plastic details are optional for every behavior.
    bank: str | None = Field(default=None, min_length=1, max_length=60)
    network: str | None = Field(default=None, min_length=1, max_length=20)
    last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    currency: str = Field(default="MXN", pattern="^[A-Z]{3}$")
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)  # TAR-08
    image: str | None = Field(
        default=None, pattern=IMAGE_PATTERN, max_length=IMAGE_MAX_LENGTH
    )  # TAR-08
    # TAR-02 credit-only fields (TDC-15: all optional, fillable later).
    statement_day: int | str | None = None  # 1-28 | "last" (TDC-02)
    cutoff_day_policy: CutoffDayPolicy = CutoffDayPolicy.include
    payment_due_days: int | None = Field(default=None, ge=1, le=30)
    payment_day: int | str | None = None  # 1-28 | "last" (TDC-04)
    credit_limit: Money | None = None
    reminder_days: list[int] | None = None  # REM-01, default [3, 1]
    opening_balance: MoneyNonNeg | None = None  # TDC-14: deuda del corte anterior
    # TAR-05 balance fields. Opening balance may be zero; only a loan's may be
    # negative (TAR-11: what you owe), checked in the service.
    initial_balance: MoneySigned | None = None
    allow_overdraft: bool = False  # TAR-09: ignored for cash (always allowed)


class AccountUpdate(BaseModel):
    """TDC-15: full edit. Only the fields sent are applied (model_dump
    exclude_unset). Account type/behavior is immutable."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    bank: str | None = Field(default=None, min_length=1, max_length=60)
    network: str | None = Field(default=None, min_length=1, max_length=20)
    last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)  # TAR-08
    image: str | None = Field(
        default=None, pattern=IMAGE_PATTERN, max_length=IMAGE_MAX_LENGTH
    )  # TAR-08
    # Credit-only (TAR-02):
    statement_day: int | str | None = None
    cutoff_day_policy: CutoffDayPolicy | None = None
    payment_due_days: int | None = Field(default=None, ge=1, le=30)
    payment_day: int | str | None = None
    credit_limit: Money | None = None
    reminder_days: list[int] | None = None
    opening_balance: MoneyNonNeg | None = None  # TDC-14: deuda del corte anterior
    # Balance accounts (TAR-05; negative only for a loan, TAR-11):
    initial_balance: MoneySigned | None = None
    allow_overdraft: bool | None = None
    is_active: bool | None = None  # TDC-12


class AccountLayoutUpdate(BaseModel):
    """TAR-07: full ordered list of account ids for the current user in the space.
    Ids not belonging to the space are ignored; missing accounts keep name order.
    `group_order` (sections) is optional: omitted keeps the saved one."""

    account_ids: list[uuid.UUID]
    group_order: list[str] | None = None


class AccountLayoutOut(BaseModel):
    """TAR-07: the user's layout; group_order always lists every section."""

    account_ids: list[uuid.UUID]
    group_order: list[str]


class CashBalanceAdjust(BaseModel):
    """TAR-09: the real cash on hand; the computed balance is set to it."""

    balance: MoneyNonNeg


class DebtSummary(BaseModel):
    """TDC-09: three numbers, never mixed."""

    statement_balance: MoneyOut
    current_cycle_spend: MoneyOut
    committed_msi: MoneyOut
    total_debt: MoneyOut


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_type_id: uuid.UUID
    name: str
    bank: str | None
    network: str | None
    last4: str | None
    currency: str
    credit_limit: Money | None
    statement_day: int | None
    statement_day_is_last: bool
    cutoff_day_policy: CutoffDayPolicy
    payment_due_days: int | None
    payment_day: int | None
    payment_day_is_last: bool
    reminder_days: list[int]
    initial_balance: MoneyOut | None  # TAR-09: a cash adjustment may make it negative
    allow_overdraft: bool
    color: str | None
    image: str | None  # TAR-08
    is_active: bool


class NextPaymentOut(BaseModel):
    """TDC-14: the nearest closed statement due — what to pay next and when."""

    amount: MoneyOut
    due_date: dt.date


class AccountWithDebtOut(AccountOut):
    behavior: AccountBehavior | None = None
    debt: DebtSummary | None = None  # TDC-09, credit only
    balance: MoneyOut | None = None  # TAR-05, balance accounts only
    signed_balance: MoneyOut | None = None  # TAR-06: +asset or -liability for PAT-01
    next_payment: NextPaymentOut | None = None  # TDC-14, credit only
    opening_balance: MoneyNonNeg | None = None  # TDC-14: synthetic previous-cut debt


class StatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    period_start: dt.date
    period_end: dt.date
    due_date: dt.date
    computed_total: MoneyOut
    applied_credit: MoneyOut
    paid_amount: MoneyOut
    status: StatementStatus
    is_overdue: bool = False  # TDC-08: flag, not a status


class PaymentCreate(BaseModel):
    """TDC-10."""

    amount: Money
    from_account_id: uuid.UUID
    date: dt.date
    statement_id: uuid.UUID | None = None


class PlanCreate(BaseModel):
    """MSI-01: convert an existing account purchase into an MSI plan."""

    transaction_id: uuid.UUID
    months: int = Field(ge=2, le=60)


class PlanCurrentInstallmentCreate(BaseModel):
    """MSI-10: registro de cuota en curso para compras MSI anteriores al sistema."""

    description: str = Field(default="", max_length=200)
    monthly_amount: Money
    currency: str = Field(default="MXN", pattern="^[A-Z]{3}$")
    account_id: uuid.UUID
    current_number: int = Field(ge=1, le=60)
    total_months: int = Field(ge=2, le=60)
    category_id: uuid.UUID
    current_is_charged: bool = True


class InstallmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    amount: Money
    estimated_charge_date: dt.date
    statement_id: uuid.UUID | None
    status: InstallmentStatus


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    transaction_id: uuid.UUID
    total_amount: Money
    months: int
    monthly_amount: Money
    start_date: dt.date
    status: PlanStatus


class PlanSummaryOut(BaseModel):
    """MSI-06 per-plan view."""

    plan: PlanOut
    description: str
    account_name: str
    paid_count: int
    charged_count: int
    pending_count: int
    remaining_amount: MoneyOut
    projected_payoff: dt.date
    projected_payment_date: dt.date
    installments: list[InstallmentOut]


class ProjectionRow(BaseModel):
    """MSI-06 global: month × account commitment."""

    account_id: uuid.UUID
    account_name: str
    month: str
    amount: Money


class MoveCycle(BaseModel):
    """TDC-06."""

    direction: str = Field(pattern="^(prev|next)$")


# Los recordatorios se exponen en app/schemas/notifications.py (REM-04..REM-07).
