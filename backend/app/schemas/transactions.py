"""Pydantic schemas for transactions (TXN-01..TXN-06, GLO-01).

GLO-01: amounts travel as strings in JSON (Decimal-safe, never float).
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models.catalogs import ExpenseNature
from app.models.transactions import TransactionType

# GLO-01: serialize Decimal as string so JS clients never touch floats.
Money = Annotated[
    Decimal,
    Field(gt=0, max_digits=14, decimal_places=2),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]
# Non-negative money: opening balances may legitimately be zero (TAR-05).
MoneyNonNeg = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]
# Output-only money: may be zero or negative (e.g. statement credit, TDC-10).
MoneyOut = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]
FxRate = Annotated[
    Decimal,
    Field(gt=0, max_digits=20, decimal_places=8),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]


class TransactionBase(BaseModel):
    type: TransactionType
    date: date
    amount: Money
    currency: str = Field(pattern="^[A-Z]{3}$")
    description: str = Field(default="", max_length=200)
    notes: str | None = None
    category_id: uuid.UUID | None = None
    payment_method_id: uuid.UUID | None = None
    payment_method_to_id: uuid.UUID | None = None
    expense_nature_override: ExpenseNature | None = None
    # FX-03: optional manual override of the frozen rate.
    fx_rate_override: FxRate | None = None
    # TDC-05a: overrides cutoff_day_policy when date == cutoff; not persisted.
    cycle_hint: Literal["current", "next"] | None = None


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(TransactionBase):
    pass


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: TransactionType
    date: date
    amount: Money
    currency: str
    fx_rate_to_base: FxRate | None
    description: str
    notes: str | None
    category_id: uuid.UUID | None
    payment_method_id: uuid.UUID | None
    payment_method_to_id: uuid.UUID | None
    card_id: uuid.UUID | None
    expense_nature_override: ExpenseNature | None
    recurring_rule_id: uuid.UUID | None
    needs_review: bool


class TransactionConfirm(BaseModel):
    """REC-03: one-tap confirm, optionally adjusting the amount."""

    amount: Money | None = None


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
