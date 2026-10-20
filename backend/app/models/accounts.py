"""Accounts and credit statements. Implements TAR-01..TAR-10, TDC-01..TDC-12, REM-01."""

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
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import AuditMixin
from app.models.catalogs import AccountType


class CutoffDayPolicy(enum.StrEnum):
    include = "include"
    next_cycle = "next_cycle"


class StatementStatus(enum.StrEnum):
    open = "open"
    closed = "closed"
    paid = "paid"
    partially_paid = "partially_paid"


class Account(Base, AuditMixin):
    """Anywhere money lives or is owed (TAR-01): credit cards, debit accounts,
    digital wallets, cash, savings, vouchers. Credit accounts (behavior=credit)
    carry the statement/cycle fields; the rest carry a stored-value balance
    (TAR-05). TDC-01: never stores PAN/CVV/expiration — only last4."""

    __tablename__ = "accounts"
    __table_args__ = (
        # CAT-01: name unique per space, accent/case-insensitive.
        UniqueConstraint("space_id", "name_normalized", name="uq_account_name"),
        # TAR-02: statement_day only for credit (NULL otherwise).
        CheckConstraint(
            "statement_day_is_last OR statement_day IS NULL "
            "OR (statement_day >= 1 AND statement_day <= 28)",
            name="ck_account_statement_day",
        ),
        # TDC-01/TAR-02: credit ⇒ exactly one of payment_due_days | payment_day;
        # non-credit ⇒ no payment rule at all.
        CheckConstraint(
            "(payment_due_days IS NULL AND payment_day IS NULL AND NOT payment_day_is_last) "
            "OR ((payment_due_days IS NOT NULL) != "
            "(payment_day IS NOT NULL OR payment_day_is_last))",
            name="ck_account_payment_rule",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # TAR-01: the account's type (CAT-08) determines its behavior.
    account_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("account_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(60), nullable=False)
    # TAR-02: plastic details, optional for every behavior.
    bank: Mapped[str | None] = mapped_column(String(60))
    network: Mapped[str | None] = mapped_column(String(20))
    last4: Mapped[str | None] = mapped_column(String(4))
    # TAR-10: every movement is in the account's currency.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MXN")

    # TAR-05: stored-value balance (NULL for credit). TAR-09: adjustable for cash.
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

    # TAR-08: visual design (presentation only). `color` is a #RRGGBB base and
    # `image` an optional front-art data URL painted on top of it.
    color: Mapped[str | None] = mapped_column(String(20))
    image: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Lets the unit of work insert a new type before its accounts (CAT-02 seed);
    # never lazy-loaded (async): read the behavior via services.accounts.
    account_type: Mapped["AccountType"] = relationship(lazy="raise")
    statements: Mapped[list["Statement"]] = relationship(back_populates="account")


class AccountLayout(Base):
    """TAR-07: per-user ordering of accounts within a space, stored as an
    ordered list of account ids plus the order of the page sections (one row
    per user+space). Accounts absent from
    the list fall back to name order at the end; ids no longer present are
    ignored. This is a personal UI preference, not shared domain data, so any
    member (incl. viewer) may set their own layout."""

    __tablename__ = "account_layouts"
    __table_args__ = (UniqueConstraint("user_id", "space_id", name="uq_account_layout_user_space"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Ordered account ids as strings (JSON-portable; UUIDs don't serialize natively).
    account_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Ordered page sections (ACCOUNT_GROUPS keys); empty = default order.
    group_order: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class Statement(Base):
    """TDC-03: a billing cycle of a credit account."""

    __tablename__ = "statements"
    __table_args__ = (
        UniqueConstraint("account_id", "period_end", name="uq_statement_period"),
        CheckConstraint("period_start <= period_end", name="ck_statement_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Statements exist only for credit accounts (TAR-02).
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
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

    account: Mapped[Account] = relationship(back_populates="statements")
