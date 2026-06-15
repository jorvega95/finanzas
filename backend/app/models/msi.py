"""Installment plans (MSI). Implements MSI-01..MSI-08."""

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import AuditMixin


class PlanStatus(enum.StrEnum):
    active = "active"
    completed = "completed"
    settled_early = "settled_early"  # MSI-07


class InstallmentStatus(enum.StrEnum):
    pending = "pending"
    charged = "charged"
    paid = "paid"
    canceled = "canceled"  # MSI-07


class InstallmentPlan(Base, AuditMixin):
    __tablename__ = "installment_plans"
    __table_args__ = (
        # MSI-01: months in [2, 60].
        CheckConstraint("months >= 2 AND months <= 60", name="ck_plan_months"),
        CheckConstraint("total_amount > 0", name="ck_plan_total_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # MSI-01: always a credit card; FK to the unified cards table.
    credit_card_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False
    )
    # MSI-03: the purchase transaction never enters aggregates by its total.
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        Enum(PlanStatus, name="plan_status", native_enum=False, length=15),
        nullable=False,
        default=PlanStatus.active,
    )

    installments: Mapped[list["Installment"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="Installment.number"
    )


class Installment(Base):
    __tablename__ = "installments"
    __table_args__ = (
        UniqueConstraint("plan_id", "number", name="uq_installment_number"),
        CheckConstraint("amount > 0", name="ck_installment_amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("installment_plans.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # MSI-04: max(purchase_date, period_start) del ciclo de esta cuota.
    # Cuota 1 = purchase_date; cuotas 2..n = period_start de su ciclo.
    estimated_charge_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    statement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("card_statements.id", ondelete="SET NULL")
    )
    status: Mapped[InstallmentStatus] = mapped_column(
        Enum(InstallmentStatus, name="installment_status", native_enum=False, length=10),
        nullable=False,
        default=InstallmentStatus.pending,
    )

    plan: Mapped[InstallmentPlan] = relationship(back_populates="installments")
