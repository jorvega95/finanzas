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


class NatureDetailItem(BaseModel):
    """DSH-06: un movimiento del drill-down (gasto directo o cuota MSI)."""

    kind: str  # transaction | msi_quota
    id: uuid.UUID
    date: dt.date
    description: str
    category_id: uuid.UUID | None
    category_name: str
    payment_method_name: str | None
    amount: MoneyOut  # en base (FX-05)
    original_amount: MoneyOut | None  # solo si la moneda ≠ base
    currency: str
    installment_number: int | None = None
    installment_total: int | None = None


class NatureDetail(BaseModel):
    """DSH-06: desglose de una naturaleza en un mes."""

    nature: str
    month: str
    total: MoneyOut
    by_category: list[CategoryBreakdownRow]
    items: list[NatureDetailItem]


class DashboardSummary(BaseModel):
    month: str
    totals: Totals  # DSH-02: ingresos/gastos/neto del mes (gasto devengado)
    by_category: list[CategoryBreakdownRow]
    by_nature: dict[str, MoneyOut]
    trend: list[TrendPoint]
    upcoming: list[UpcomingItem]


class ForecastEvent(BaseModel):
    """PRO-03/04/05: un evento fechado del flujo proyectado."""

    date: dt.date
    kind: str
    direction: str  # in | out
    description: str
    amount: MoneyOut  # base, magnitud positiva
    currency: str  # moneda original
    is_estimate: bool
    covered: bool
    shortfall: MoneyOut
    balance_after: MoneyOut


class ForecastAlert(BaseModel):
    """PRO-05: una obligación que el flujo no alcanza a cubrir."""

    date: dt.date
    description: str
    shortfall: MoneyOut


class ForecastSummary(BaseModel):
    """PRO-01..06: pronóstico de flujo a futuro."""

    horizon_months: int
    generated_for: dt.date
    starting_cash: MoneyOut  # PRO-02
    cash_adjustment: MoneyOut
    ending_balance: MoneyOut
    min_balance: MoneyOut
    min_balance_date: dt.date | None
    first_overdraft_date: dt.date | None  # PRO-05
    total_shortfall: MoneyOut
    events: list[ForecastEvent]
    alerts: list[ForecastAlert]


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
