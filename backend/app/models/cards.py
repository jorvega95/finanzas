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


class Card(Base, AuditMixin):
    """A card of any type (TAR-01). Credit cards (behavior=credit) carry the
    statement/cycle fields; debit/prepaid carry a stored-value balance (TAR-05).
    TDC-01: never stores PAN/CVV/expiration — only last4."""

    __tablename__ = "cards"
    __table_args__ = (
        # TAR-02: statement_day only for credit (NULL otherwise).
        CheckConstraint(
            "statement_day_is_last OR statement_day IS NULL "
            "OR (statement_day >= 1 AND statement_day <= 28)",
            name="ck_card_statement_day",
        ),
        # TDC-01/TAR-02: credit ⇒ exactly one of payment_due_days | payment_day;
        # non-credit ⇒ no payment rule at all.
        CheckConstraint(
            "(payment_due_days IS NULL AND payment_day IS NULL AND NOT payment_day_is_last) "
            "OR ((payment_due_days IS NOT NULL) != "
            "(payment_day IS NOT NULL OR payment_day_is_last))",
            name="ck_card_payment_rule",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # TAR-01: the card's type (CAT-08) determines its behavior.
    card_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("card_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(60), nullable=False)
    bank: Mapped[str] = mapped_column(String(60), nullable=False)
    network: Mapped[str] = mapped_column(String(20), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MXN")

    # TAR-05: stored-value balance for debit/prepaid (NULL for credit).
    initial_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    allow_overdraft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # TDC-01 (credit only): credit limit.
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    # TDC-02: 1-28 or last (credit only).
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


class CardLayout(Base):
    """TAR-07: per-user ordering of cards within a space, stored as an ordered
    list of card ids (one row per user+space). Cards absent from the list fall
    back to alias order at the end; ids no longer present are ignored. This is a
    personal UI preference, not shared domain data, so any member (incl. viewer)
    may set their own layout."""

    __tablename__ = "card_layouts"
    __table_args__ = (UniqueConstraint("user_id", "space_id", name="uq_card_layout_user_space"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Ordered card ids as strings (JSON-portable; UUIDs don't serialize natively).
    card_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


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
    # Statements exist only for credit cards, hence the explicit name.
    credit_card_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # TDC-07: charges + MSI installments − payments − applied credit, set at close.
    computed_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # TDC-14: manually captured previous-cut debt, kept separate from itemized
    # charges so a later late charge/refund (TDC-06/TDC-16) doesn't wipe it out
    # when computed_total is recomputed. NULL for statements without one.
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
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

    card: Mapped[Card] = relationship(back_populates="statements")
