"""Pydantic schemas for recurring rules (REC-01..REC-05)."""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.recurring import RecurringFrequency
from app.models.transactions import TransactionType
from app.schemas.transactions import Money


class RecurringRuleBase(BaseModel):
    type: TransactionType
    amount: Money
    amount_is_estimate: bool = False
    currency: str = Field(pattern="^[A-Z]{3}$")
    description: str = Field(min_length=1, max_length=200)
    category_id: uuid.UUID | None = None
    payment_method_id: uuid.UUID | None = None
    frequency: RecurringFrequency
    start_date: date
    end_date: date | None = None
    max_occurrences: int | None = Field(default=None, ge=1)
    month_day: int | None = Field(default=None, ge=1, le=31)
    use_last_day: bool = False


class RecurringRuleCreate(RecurringRuleBase):
    pass


class RecurringRuleUpdate(BaseModel):
    """REC-04: edits only affect future instances."""

    amount: Money | None = None
    amount_is_estimate: bool | None = None
    description: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: uuid.UUID | None = None
    payment_method_id: uuid.UUID | None = None
    end_date: date | None = None
    max_occurrences: int | None = Field(default=None, ge=1)
    month_day: int | None = Field(default=None, ge=1, le=31)
    use_last_day: bool | None = None
    is_active: bool | None = None


class RecurringRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: TransactionType
    amount: Money
    amount_is_estimate: bool
    currency: str
    description: str
    category_id: uuid.UUID | None
    payment_method_id: uuid.UUID | None
    frequency: RecurringFrequency
    start_date: date
    end_date: date | None
    max_occurrences: int | None
    month_day: int | None
    use_last_day: bool
    is_active: bool
