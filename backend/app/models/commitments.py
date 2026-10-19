"""Commitments with vendors. Implements CXP-01/CXP-02 (a contracted service
with a balance to settle; abonos are expenses linked by commitment_id)."""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import AuditMixin, TimestampMixin


class Commitment(Base, AuditMixin):
    """CXP-01: what was agreed with a vendor. Paid/pending are computed (SQL),
    never stored: paid = paid_before_tracking + Σ linked expenses (CXP-03)."""

    __tablename__ = "commitments"
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_commitment_total_positive"),
        CheckConstraint(
            "paid_before_tracking >= 0 AND paid_before_tracking <= total_amount",
            name="ck_commitment_paid_before",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # vendor / concept
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="RESTRICT"), index=True
    )
    # Default expense category for its abonos.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="SET NULL")
    )
    # What was paid before using the app (no invented past transactions).
    paid_before_tracking: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00")
    )
    due_date: Mapped[dt.date | None] = mapped_column(Date)  # final settlement date
    notes: Mapped[str | None] = mapped_column(Text)
    is_canceled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    payments: Mapped[list["CommitmentPayment"]] = relationship(
        back_populates="commitment",
        cascade="all, delete-orphan",
        order_by="CommitmentPayment.due_date",
    )


class CommitmentPayment(Base, TimestampMixin):
    """CXP-02: optional payment schedule. Coverage is computed (FIFO by date)."""

    __tablename__ = "commitment_payments"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_commitment_payment_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    commitment: Mapped[Commitment] = relationship(back_populates="payments")
