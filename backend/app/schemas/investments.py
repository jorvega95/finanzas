"""Pydantic schemas for investments and net worth (INV-01..06, PAT-01)."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models.investments import AccountKind, MovementType
from app.schemas.transactions import MoneyOut

# INV-01: crypto quantities carry up to 10 decimals; serialized as strings.
Quantity = Annotated[
    Decimal,
    Field(gt=0, max_digits=28, decimal_places=10),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]
QuantityOut = Annotated[
    Decimal, PlainSerializer(lambda v: str(v), return_type=str, when_used="json")
]
Price = Annotated[
    Decimal,
    Field(gt=0, max_digits=20, decimal_places=8),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]
PriceOut = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str, when_used="json")]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: AccountKind


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: AccountKind
    is_active: bool


class MovementCreate(BaseModel):
    """INV-02."""

    type: MovementType
    asset_symbol: str = Field(min_length=1, max_length=60)
    asset_name: str = Field(default="", max_length=80)
    quantity: Quantity
    price: Price | None = None
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    date: dt.date


class HoldingValuation(BaseModel):
    holding_id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    kind: str
    asset_symbol: str
    asset_name: str
    quantity: QuantityOut
    avg_cost: PriceOut
    currency: str
    price: PriceOut | None
    price_fetched_at: dt.datetime | None  # INV-03: "precio de hace 2 h"
    price_source: str | None
    value_base: MoneyOut | None
    unrealized_pnl: MoneyOut | None
    realized_pnl: MoneyOut


class PortfolioOut(BaseModel):
    """INV-06: separa P&L realizado y no realizado."""

    total_value: MoneyOut
    total_unrealized_pnl: MoneyOut
    total_realized_pnl: MoneyOut
    holdings: list[HoldingValuation]


class ManualPrice(BaseModel):
    """INV-04."""

    symbol: str = Field(min_length=1, max_length=60)
    price: Price
    currency: str = Field(default="MXN", pattern="^[A-Z]{3}$")


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: dt.date
    total_value: MoneyOut


class NetWorthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: dt.date
    assets: MoneyOut
    liabilities: MoneyOut
    net_worth: MoneyOut
