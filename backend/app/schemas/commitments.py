"""Pydantic schemas for vendor commitments (CXP-01..CXP-05). GLO-01: money as strings."""

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.transactions import Money, MoneyNonNeg, MoneyOut, TransactionOut


class SchedulePaymentIn(BaseModel):
    due_date: dt.date
    amount: Money


class CommitmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    total_amount: Money
    currency: str = Field(default="MXN", pattern="^[A-Z]{3}$")
    event_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None  # default category for its abonos
    paid_before_tracking: MoneyNonNeg = Field(default=Decimal("0.00"))
    due_date: dt.date | None = None
    notes: str | None = None
    schedule: list[SchedulePaymentIn] = Field(default_factory=list)  # CXP-02


class CommitmentUpdate(BaseModel):
    """Only the fields sent are applied; `schedule`, when sent, replaces it."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    total_amount: Money | None = None
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    event_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    paid_before_tracking: MoneyNonNeg | None = None
    due_date: dt.date | None = None
    notes: str | None = None
    is_canceled: bool | None = None
    schedule: list[SchedulePaymentIn] | None = None


class ScheduleRowOut(BaseModel):
    """CXP-02: computed FIFO coverage of each scheduled payment."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    due_date: dt.date
    amount: MoneyOut
    covered: MoneyOut
    uncovered: MoneyOut
    is_covered: bool
    is_overdue: bool


class CommitmentOut(BaseModel):
    id: uuid.UUID
    name: str
    total_amount: MoneyOut
    currency: str
    event_id: uuid.UUID | None
    category_id: uuid.UUID | None
    paid_before_tracking: MoneyOut
    due_date: dt.date | None
    notes: str | None
    is_canceled: bool
    # CXP-03/05 (computed):
    paid: MoneyOut
    pending: MoneyOut
    status: str  # pending | paid | canceled
    is_overdue: bool
    abonos: int
    schedule: list[ScheduleRowOut]
    unscheduled_pending: MoneyOut


class ThirdPartyPayment(BaseModel):
    """CXP-04: someone paid the vendor directly as a gift."""

    amount: Money
    date: dt.date
    account_id: uuid.UUID
    description: str = Field(default="", max_length=200)
    category_id: uuid.UUID | None = None  # expense category; default the commitment's


class ThirdPartyOut(BaseModel):
    income: TransactionOut
    expense: TransactionOut
    commitment: CommitmentOut
