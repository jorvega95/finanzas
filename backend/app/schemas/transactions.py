"""Pydantic schemas for transactions (TXN-01..TXN-14, GLO-01).

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
# Signed money: a loan's opening balance is negative when you owe (TAR-11).
MoneySigned = Annotated[
    Decimal,
    Field(max_digits=14, decimal_places=2),
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
    account_id: uuid.UUID  # TAR-03
    account_to_id: uuid.UUID | None = None  # TXN-02: transfer target
    # TXN-13: what enters the target when its currency differs from the source.
    amount_to: Money | None = None
    # TXN-14: fee charged to the source account (stored as a child expense).
    fee_amount: Money | None = None
    expense_nature_override: ExpenseNature | None = None
    # FX-03: optional manual override of the frozen rate.
    fx_rate_override: FxRate | None = None
    # TDC-05a: overrides cutoff_day_policy when date == cutoff; not persisted.
    cycle_hint: Literal["current", "next"] | None = None
    # TXN-09: explicit statement to pay when account_to is a credit account.
    target_statement_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None  # EVT-02: at most one event


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
    account_id: uuid.UUID
    account_to_id: uuid.UUID | None
    amount_to: Money | None  # TXN-13
    fee_amount: Money | None = None  # TXN-14: fee of this transfer (set by the router)
    fee_for_id: uuid.UUID | None  # TXN-14: set on the fee row itself
    statement_id: uuid.UUID | None  # TXN-09: set when transfer is a TDC payment
    expense_nature_override: ExpenseNature | None
    recurring_rule_id: uuid.UUID | None
    needs_review: bool
    event_id: uuid.UUID | None = None  # EVT-02
    installment_plan_id: uuid.UUID | None = None  # MSI-03: set on an MSI parent


class TransactionEventUpdate(BaseModel):
    """EVT-02: link (or unlink with null) a transaction to an event."""

    event_id: uuid.UUID | None


class TransactionConfirm(BaseModel):
    """REC-03: one-tap confirm, optionally adjusting the amount."""

    amount: Money | None = None


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
