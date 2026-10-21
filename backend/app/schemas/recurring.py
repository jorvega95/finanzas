"""Pydantic schemas for recurring rules and subscriptions (REC-01..REC-13)."""

import datetime as dt
import uuid
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.recurring import RecurringFrequency, RecurringKind
from app.models.transactions import TransactionType
from app.schemas.transactions import Money, MoneyOut

# REC-12: 0–3 values, each 0..30 days before the charge.
ReminderDays = Annotated[list[Annotated[int, Field(ge=0, le=30)]], Field(max_length=3)]
RuleStatus = Literal["active", "trial", "paused", "canceled"]


def _http_url(value: str | None) -> str | None:
    """REC-07: the cancel link is rendered as <a href>; only http(s) so a
    `javascript:` URL can never run (XSS)."""
    if value is None:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ValueError("La liga debe empezar con http:// o https://")
    return value.strip()


CancelUrl = Annotated[str | None, Field(default=None, max_length=500), AfterValidator(_http_url)]


class RecurringRuleBase(BaseModel):
    kind: RecurringKind = RecurringKind.generic  # REC-07
    type: TransactionType
    # REC-11: optional only for bills (estimate).
    amount: Money | None = None
    amount_is_estimate: bool = False
    # REC-08: currency of the price (may differ from the account's on expenses).
    currency: str = Field(pattern="^[A-Z]{3}$")
    description: str = Field(min_length=1, max_length=200)
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID  # TAR-03
    frequency: RecurringFrequency
    start_date: date
    end_date: date | None = None
    max_occurrences: int | None = Field(default=None, ge=1)
    month_day: int | None = Field(default=None, ge=1, le=31)
    use_last_day: bool = False
    is_trial: bool = False  # REC-10
    reminder_days: ReminderDays | None = None  # REC-12: None = default per kind
    cancel_url: CancelUrl = None
    notes: str | None = Field(default=None, max_length=2000)


class RecurringRuleCreate(RecurringRuleBase):
    pass


class RecurringRuleUpdate(BaseModel):
    """REC-04: edits only affect future instances."""

    amount: Money | None = None
    amount_is_estimate: bool | None = None
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    description: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    end_date: date | None = None
    max_occurrences: int | None = Field(default=None, ge=1)
    month_day: int | None = Field(default=None, ge=1, le=31)
    use_last_day: bool | None = None
    is_active: bool | None = None
    reminder_days: ReminderDays | None = None
    cancel_url: CancelUrl = None
    notes: str | None = Field(default=None, max_length=2000)


class RecurringRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: RecurringKind
    type: TransactionType
    amount: Money | None
    amount_is_estimate: bool
    currency: str
    description: str
    category_id: uuid.UUID | None
    account_id: uuid.UUID
    frequency: RecurringFrequency
    start_date: date
    end_date: date | None
    max_occurrences: int | None
    month_day: int | None
    use_last_day: bool
    is_active: bool
    is_trial: bool
    canceled_at: date | None
    reminder_days: list[int]
    cancel_url: str | None
    notes: str | None
    # Derived (REC-09) and next scheduled date >= today.
    status: RuleStatus = "active"
    next_date: date | None = None
    # REC-08: price in the account currency at today's rate (informative).
    account_currency: str | None = None
    account_amount_today: MoneyOut | None = None


class PendingBillOut(BaseModel):
    """REC-11: one bill occurrence waiting for its amount."""

    rule_id: uuid.UUID
    description: str
    scheduled_date: date
    estimate: Money | None
    currency: str
    account_id: uuid.UUID
    category_id: uuid.UUID | None


class BillCapture(BaseModel):
    scheduled_date: date
    amount: Money
    date: dt.date | None = None  # default: scheduled_date


class BillSkip(BaseModel):
    scheduled_date: date


class SubscriptionSummaryOut(BaseModel):
    """REC-13: monthly-equivalent cost of active + trial subscriptions."""

    monthly_total: MoneyOut
    yearly_total: MoneyOut
    currency: str
    is_approximate: bool
    missing_rate: bool
    active_count: int
    trial_count: int
    paused_count: int
    canceled_count: int
