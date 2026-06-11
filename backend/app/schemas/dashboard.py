"""Pydantic schemas for dashboard and budgets (DSH-01..05, PRE-01..04)."""

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.transactions import Money, MoneyOut


class Totals(BaseModel):
    income: MoneyOut
    expenses: MoneyOut
    net: MoneyOut


class CategoryBreakdownRow(BaseModel):
    category_id: uuid.UUID | None
    category_name: str
    total: MoneyOut


class TrendPoint(Totals):
    month: str


class UpcomingItem(BaseModel):
    """DSH-05."""

    kind: str
    date: dt.date
    description: str
    amount: MoneyOut
    ref_id: uuid.UUID
    is_overdue: bool


class DashboardSummary(BaseModel):
    month: str
    accrual: Totals  # DSH-04: devengado (default)
    cash_flow: Totals  # DSH-04: flujo de caja
    by_category: list[CategoryBreakdownRow]
    by_nature: dict[str, MoneyOut]
    trend: list[TrendPoint]
    upcoming: list[UpcomingItem]


class BudgetCreate(BaseModel):
    category_id: uuid.UUID
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    amount: Money
    alert_threshold: Decimal = Field(default=Decimal("0.80"), gt=0, le=1)


class BudgetUpdate(BaseModel):
    amount: Money | None = None
    alert_threshold: Decimal | None = Field(default=None, gt=0, le=1)


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    month: dt.date
    amount: Money
    alert_threshold: Decimal


class BudgetProgressOut(BaseModel):
    """PRE-04."""

    budget: BudgetOut
    category_name: str
    consumed: MoneyOut
    remaining: MoneyOut


class BudgetCopy(BaseModel):
    from_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    to_month: str = Field(pattern=r"^\d{4}-\d{2}$")
