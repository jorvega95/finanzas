"""Recurring rules. Implements REC-01..REC-05."""

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import AuditMixin
from app.models.transactions import TransactionType


class RecurringFrequency(enum.StrEnum):
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    yearly = "yearly"


class RecurringRule(Base, AuditMixin):
    """REC-01: transaction template + schedule. Explicit columns instead of
    jsonb so SQLite tests and Postgres behave identically."""

    __tablename__ = "recurring_rules"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_rule_amount_positive"),
        CheckConstraint(
            "month_day IS NULL OR (month_day >= 1 AND month_day <= 31)", name="ck_rule_month_day"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Template (REC-01).
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", native_enum=False, length=10),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # REC-03: variable bills (electricity/water) are estimates to adjust.
    amount_is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT")
    )
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payment_methods.id", ondelete="RESTRICT")
    )

    # Schedule (REC-01).
    frequency: Mapped[RecurringFrequency] = mapped_column(
        Enum(RecurringFrequency, name="recurring_frequency", native_enum=False, length=10),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    max_occurrences: Mapped[int | None] = mapped_column(Integer)
    # Monthly day rule: day N clamped to month end, or last day of month.
    month_day: Mapped[int | None] = mapped_column(Integer)
    use_last_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RecurringTombstone(Base):
    """REC-03: a discarded instance leaves a tombstone so REC-02 never
    regenerates it."""

    __tablename__ = "recurring_tombstones"
    __table_args__ = (UniqueConstraint("rule_id", "scheduled_date", name="uq_tombstone"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recurring_rules.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
