"""Credit cards and statements. Implements TDC-01..TDC-12, REM-01."""

import datetime as dt
import enum
import uuid
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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import AuditMixin


class CutoffDayPolicy(enum.StrEnum):
    include = "include"
    next_cycle = "next_cycle"


class StatementStatus(enum.StrEnum):
    open = "open"
    closed = "closed"
    paid = "paid"
    partially_paid = "partially_paid"


class CreditCard(Base, AuditMixin):
    """TDC-01: never stores PAN/CVV/expiration — only last4."""

    __tablename__ = "credit_cards"
    __table_args__ = (
        CheckConstraint(
            "statement_day_is_last OR (statement_day >= 1 AND statement_day <= 28)",
            name="ck_card_statement_day",
        ),
        # TDC-01: exactly one of payment_due_days | payment_day(/last).
        CheckConstraint(
            "(payment_due_days IS NOT NULL) != (payment_day IS NOT NULL OR payment_day_is_last)",
            name="ck_card_payment_rule",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(60), nullable=False)
    bank: Mapped[str] = mapped_column(String(60), nullable=False)
    network: Mapped[str] = mapped_column(String(20), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MXN")
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    # TDC-02: 1-28 or last.
    statement_day: Mapped[int | None] = mapped_column(Integer)
    statement_day_is_last: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # TDC-05.
    cutoff_day_policy: Mapped[CutoffDayPolicy] = mapped_column(
        Enum(CutoffDayPolicy, name="cutoff_day_policy", native_enum=False, length=12),
        nullable=False,
        default=CutoffDayPolicy.include,
    )
    # TDC-04: exactly one representation.
    payment_due_days: Mapped[int | None] = mapped_column(Integer)
    payment_day: Mapped[int | None] = mapped_column(Integer)
    payment_day_is_last: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # REM-01: offsets in days before due_date.
    reminder_days: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=lambda: [3, 1])

    color: Mapped[str | None] = mapped_column(String(20))
    icon: Mapped[str | None] = mapped_column(String(40))
    # CAT-07: auto-created payment method linked to this card.
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    statements: Mapped[list["CardStatement"]] = relationship(back_populates="card")


class CardStatement(Base):
    __tablename__ = "card_statements"
    __table_args__ = (
        UniqueConstraint("credit_card_id", "period_end", name="uq_statement_period"),
        CheckConstraint("period_start <= period_end", name="ck_statement_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credit_card_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("credit_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # TDC-07: charges + MSI installments − payments − applied credit, set at close.
    computed_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # TDC-10: credit carried over from the previous statement's overpayment.
    applied_credit: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # TDC-08: paid/partially_paid; overdue is a flag computed against today.
    status: Mapped[StatementStatus] = mapped_column(
        Enum(StatementStatus, name="statement_status", native_enum=False, length=15),
        nullable=False,
        default=StatementStatus.open,
    )

    card: Mapped[CreditCard] = relationship(back_populates="statements")
