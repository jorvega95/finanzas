"""Recurring rules and subscriptions. Implements REC-01..REC-13."""

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import AuditMixin
from app.models.transactions import TransactionType


class RecurringFrequency(enum.StrEnum):
    weekly = "weekly"
    biweekly = "biweekly"  # REC-01: "catorcena", start_date + 14 días continuos.
    semimonthly = "semimonthly"  # REC-06: quincena fiscal, días 15 y último de cada mes.
    monthly = "monthly"
    bimonthly = "bimonthly"  # REC-06b: every 2 months, same day rule as monthly.
    yearly = "yearly"


class RecurringKind(enum.StrEnum):
    """REC-07: generic (payroll, rent), subscription (fixed price) or bill
    (variable amount captured by the user, REC-11)."""

    generic = "generic"
    subscription = "subscription"
    bill = "bill"


class RecurringRule(Base, AuditMixin):
    """REC-01: transaction template + schedule. Explicit columns instead of
    jsonb so SQLite tests and Postgres behave identically."""

    __tablename__ = "recurring_rules"
    __table_args__ = (
        CheckConstraint("amount IS NULL OR amount > 0", name="ck_rule_amount_positive"),
        # REC-11: only bills may omit the amount (it is just an estimate there).
        CheckConstraint("kind = 'bill' OR amount IS NOT NULL", name="ck_rule_amount_required"),
        CheckConstraint(
            "month_day IS NULL OR (month_day >= 1 AND month_day <= 31)", name="ck_rule_month_day"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[RecurringKind] = mapped_column(
        Enum(RecurringKind, name="recurring_kind", native_enum=False, length=12),
        nullable=False,
        default=RecurringKind.generic,
    )

    # Template (REC-01).
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", native_enum=False, length=10),
        nullable=False,
    )
    # REC-11: NULL only for bills without an estimate.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # REC-03: variable bills (electricity/water) are estimates to adjust.
    amount_is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # REC-08: currency of the price; may differ from the account's on expenses.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT")
    )
    # TAR-03: account the instances are charged to / received into.
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )

    # Schedule (REC-01).
    frequency: Mapped[RecurringFrequency] = mapped_column(
        Enum(RecurringFrequency, name="recurring_frequency", native_enum=False, length=12),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    max_occurrences: Mapped[int | None] = mapped_column(Integer)
    # Monthly day rule: day N clamped to month end, or last day of month.
    month_day: Mapped[int | None] = mapped_column(Integer)
    use_last_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # REC-09: canceled keeps history and can be reverted.
    canceled_at: Mapped[date | None] = mapped_column(Date)
    # REC-10: free trial; start_date is the trial end = first charge.
    is_trial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # REC-12: days before each charge to notify.
    reminder_days: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    cancel_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)


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
