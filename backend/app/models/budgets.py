"""Budgets. Implements PRE-01..PRE-04."""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import AuditMixin


class Budget(Base, AuditMixin):
    """PRE-01: (root category, month, amount in base currency, threshold).
    `month` is stored as the first day of the month (GLO-02)."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("space_id", "category_id", "month", name="uq_budget"),
        CheckConstraint("amount > 0", name="ck_budget_amount"),
        CheckConstraint("alert_threshold > 0 AND alert_threshold <= 1", name="ck_budget_threshold"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[dt.date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    alert_threshold: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.80")
    )
