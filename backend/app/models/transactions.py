"""Transactions. Implements TXN-01..TXN-06, FX-03, REC-02/03, GLO-01/02/04."""

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

    # TXN-01: required for expense/income, NULL for transfer.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT")
    )
    # CAT-03: per-transaction override of the category's nature.
    expense_nature_override: Mapped[ExpenseNature | None] = mapped_column(
        Enum(ExpenseNature, name="expense_nature", native_enum=False, length=15)
    )
    # TXN-02: for transfers this is the source; payment_method_to_id the target.
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payment_methods.id", ondelete="RESTRICT")
    )
    payment_method_to_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payment_methods.id", ondelete="RESTRICT")
    )

    # TDC (Fase 2): derived from the payment method when type=credit_card.
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
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
