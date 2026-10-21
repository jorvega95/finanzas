"""Transactions. Implements TXN-01..TXN-06, TXN-13/14, FX-03, REC-02/03, EVT-02, CXP-03,
GLO-01/02/04."""

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import AuditMixin
from app.models.catalogs import ExpenseNature


class TransactionType(enum.StrEnum):
    expense = "expense"
    income = "income"
    transfer = "transfer"


class Transaction(Base, AuditMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        # GLO-01: money is NUMERIC(14,2), always positive (sign comes from type).
        CheckConstraint("amount > 0", name="ck_txn_amount_positive"),
        # TXN-13: received amount of a cross-currency transfer, positive if set.
        CheckConstraint("amount_to IS NULL OR amount_to > 0", name="ck_txn_amount_to_positive"),
        # REC-02: re-running the recurring job can never duplicate an instance
        # (NULLs don't collide, so manual transactions are unaffected).
        UniqueConstraint("recurring_rule_id", "scheduled_date", name="uq_txn_recurrence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", native_enum=False, length=10),
        nullable=False,
    )
    # GLO-02: business date, never datetime. (`dt.date` because this very
    # attribute shadows the `date` name inside the class body.)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # FX-03: rate frozen at creation/edit; aggregates never re-query history.
    # NULL when currency == space.base_currency (rate 1).
    fx_rate_to_base: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    # REC-08: price of a recurring charge in another currency (e.g. 20 USD
    # billed in MXN). Informational only: never part of any aggregate.
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    original_currency: Mapped[str | None] = mapped_column(String(3))

    # TXN-01: required for expense/income, NULL for transfer.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT")
    )
    # CAT-03: per-transaction override of the category's nature.
    expense_nature_override: Mapped[ExpenseNature | None] = mapped_column(
        Enum(ExpenseNature, name="expense_nature", native_enum=False, length=15)
    )
    # TAR-03: the account paid from / received into. TXN-02: for transfers this
    # is the source and account_to_id the target.
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_to_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    # TXN-13: what enters the target account, in its currency, when it differs
    # from the source currency. NULL for same-currency transfers.
    amount_to: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # TXN-14: an expense row that is the fee of this transfer points to it.
    fee_for_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    # EVT-02: at most one event per transaction (grouping only; no effect on
    # what counts as income/expense, TXN-02/MSI-03).
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="RESTRICT"), index=True
    )
    # CXP-03: an expense that is an abono to a vendor commitment.
    commitment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("commitments.id", ondelete="RESTRICT"), index=True
    )

    # TDC-05: billing cycle this charge (or payment, TDC-10) belongs to.
    # Only credit charges get a statement; debit/prepaid never do (TAR-04).
    statement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # MSI-03: set on the parent purchase; excluded from all aggregates.
    installment_plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    # REC-02/03: provenance of generated instances.
    recurring_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("recurring_rules.id", ondelete="SET NULL")
    )
    scheduled_date: Mapped[dt.date | None] = mapped_column(Date)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # IMP (Fase 6).
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    # GLO-04: transactions additionally track updated_by.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("profiles.id"))
