"""Pydantic schemas for events (EVT-01..EVT-03). GLO-01: money as strings."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.dashboard import CategoryBreakdownRow
from app.schemas.transactions import Money, MoneyOut


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    date: dt.date | None = None
    budget: Money | None = None  # in the space's base currency
    notes: str | None = None


class EventUpdate(BaseModel):
    """Only the fields sent are applied (exclude_unset)."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    date: dt.date | None = None
    budget: Money | None = None
    notes: str | None = None
    is_active: bool | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    date: dt.date | None
    budget: Money | None
    notes: str | None
    is_active: bool


class EventLoanOut(BaseModel):
    """TAR-11: a loan with movements linked to the event and its balance today."""

    model_config = ConfigDict(from_attributes=True)

    account_id: uuid.UUID
    name: str
    currency: str
    balance: MoneyOut  # negative = you owe


class EventSummaryOut(BaseModel):
    """EVT-03: totals in base currency (frozen rates, FX-03)."""

    event: EventOut
    spent: MoneyOut
    received: MoneyOut
    net: MoneyOut
    budget_remaining: MoneyOut | None
    movements: int
    by_category: list[CategoryBreakdownRow]
    loans: list[EventLoanOut]
