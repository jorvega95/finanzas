"""Categories and payment methods. Implements CAT-01..CAT-07, GLO-03, GLO-05."""

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import AuditMixin


class CategoryKind(enum.StrEnum):
    expense = "expense"
    income = "income"


class ExpenseNature(enum.StrEnum):
    fixed = "fixed"
    variable = "variable"
    discretionary = "discretionary"


class PaymentMethodType(enum.StrEnum):
    cash = "cash"
    debit = "debit"
    credit_card = "credit_card"
    prepaid = "prepaid"  # CAT-07: vales/regalo y demás prepago
    transfer = "transfer"
    other = "other"


class CardBehavior(enum.StrEnum):
    """CAT-08: system classifier driving the card engine (TAR-01)."""

    credit = "credit"  # deuda, ciclos, statements, MSI (TDC)
    debit = "debit"  # saldo de valor almacenado (TAR-05)
    prepaid = "prepaid"  # vales/regalo: saldo de valor almacenado (TAR-05)


class CardType(Base, AuditMixin):
    """CAT-08: per-space catalog of card types. The name is free/editable;
    the behavior is a fixed system classifier the engine depends on."""

    __tablename__ = "card_types"
    __table_args__ = (UniqueConstraint("space_id", "name_normalized", name="uq_card_type_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(60), nullable=False)
    behavior: Mapped[CardBehavior] = mapped_column(
        Enum(CardBehavior, name="card_behavior", native_enum=False, length=10),
        nullable=False,
    )
    icon: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(20))
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Category(Base, AuditMixin):
    __tablename__ = "categories"
    __table_args__ = (
        # CAT-01: unique per space + kind, accent/case-insensitive via
        # name_normalized (Python-side normalization, portable across DBs).
        UniqueConstraint("space_id", "kind", "name_normalized", name="uq_category_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(60), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[CategoryKind] = mapped_column(
        Enum(CategoryKind, name="category_kind", native_enum=False, length=10),
        nullable=False,
    )
    # CAT-03: only expense categories carry a nature (nullable for income).
    expense_nature: Mapped[ExpenseNature | None] = mapped_column(
        Enum(ExpenseNature, name="expense_nature", native_enum=False, length=15)
    )
    # CAT-06: max 2 levels (validated in service).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT")
    )
    # IMP-03: hidden seed category "Sin categoría" is not user-facing.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    parent: Mapped["Category | None"] = relationship(remote_side=[id])


class PaymentMethod(Base, AuditMixin):
    __tablename__ = "payment_methods"
    __table_args__ = (
        # CAT-01: unique per space, accent/case-insensitive.
        UniqueConstraint("space_id", "name_normalized", name="uq_payment_method_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(60), nullable=False)
    type: Mapped[PaymentMethodType] = mapped_column(
        Enum(PaymentMethodType, name="payment_method_type", native_enum=False, length=15),
        nullable=False,
    )
    # CAT-07/TAR-03: a card-linked method references its card (any type).
    card_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
