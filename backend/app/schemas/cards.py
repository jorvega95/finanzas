"""Pydantic schemas for cards, statements, MSI and reminders (Fase 2)."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.cards import CutoffDayPolicy, StatementStatus
from app.models.msi import InstallmentStatus, PlanStatus
from app.models.reminders import ReminderChannel, ReminderKind, ReminderStatus
from app.schemas.transactions import Money, MoneyOut


class CardCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=60)
    bank: str = Field(min_length=1, max_length=60)
    network: str = Field(min_length=1, max_length=20)
    last4: str = Field(pattern=r"^\d{4}$")
    statement_day: int | str  # 1-28 | "last" (TDC-02)
    cutoff_day_policy: CutoffDayPolicy = CutoffDayPolicy.include
    payment_due_days: int | None = Field(default=None, ge=1, le=30)
    payment_day: int | str | None = None  # 1-28 | "last" (TDC-04)
    credit_limit: Money | None = None
    currency: str = Field(default="MXN", pattern="^[A-Z]{3}$")
    reminder_days: list[int] | None = None  # REM-01, default [3, 1]
    color: str | None = Field(default=None, max_length=20)


class CardUpdate(BaseModel):
    alias: str | None = Field(default=None, min_length=1, max_length=60)
    credit_limit: Money | None = None
    reminder_days: list[int] | None = None
    color: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None  # TDC-12


class DebtSummary(BaseModel):
    """TDC-09: three numbers, never mixed."""

    statement_balance: MoneyOut
    current_cycle_spend: MoneyOut
    committed_msi: MoneyOut
    total_debt: MoneyOut


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alias: str
    bank: str
    network: str
    last4: str
    currency: str
    credit_limit: Money | None
    statement_day: int | None
    statement_day_is_last: bool
    cutoff_day_policy: CutoffDayPolicy
    payment_due_days: int | None
    payment_day: int | None
    payment_day_is_last: bool
    reminder_days: list[int]
    color: str | None
    payment_method_id: uuid.UUID | None
    is_active: bool


class CardWithDebtOut(CardOut):
    debt: DebtSummary | None = None


class StatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    credit_card_id: uuid.UUID
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
    from_payment_method_id: uuid.UUID
    date: dt.date
    statement_id: uuid.UUID | None = None


class PlanCreate(BaseModel):
    """MSI-01: convert an existing card purchase into an MSI plan."""

    transaction_id: uuid.UUID
    months: int = Field(ge=2, le=60)


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
    credit_card_id: uuid.UUID
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
    card_alias: str
    paid_count: int
    charged_count: int
    pending_count: int
    remaining_amount: MoneyOut
    projected_payoff: dt.date
    installments: list[InstallmentOut]


class ProjectionRow(BaseModel):
    """MSI-06 global: month × card commitment."""

    credit_card_id: uuid.UUID
    card_alias: str
    month: str
    amount: Money


class MoveCycle(BaseModel):
    """TDC-06."""

    direction: str = Field(pattern="^(prev|next)$")


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ReminderKind
    fire_at: dt.date
    channel: ReminderChannel
    message: str
    status: ReminderStatus
