"""Import every model here so Alembic autogenerate sees the full metadata."""

from app.db.base import Base
from app.models.catalogs import (
    Category,
    CategoryKind,
    ExpenseNature,
    PaymentMethod,
    PaymentMethodType,
)
from app.models.fx import ExchangeRate
from app.models.recurring import RecurringFrequency, RecurringRule, RecurringTombstone
from app.models.spaces import Profile, Space, SpaceMember, SpaceRole, SpaceType
from app.models.transactions import Transaction, TransactionType

__all__ = [
    "Base",
    "Category",
    "CategoryKind",
    "ExchangeRate",
    "ExpenseNature",
    "PaymentMethod",
    "PaymentMethodType",
    "Profile",
    "RecurringFrequency",
    "RecurringRule",
    "RecurringTombstone",
    "Space",
    "SpaceMember",
    "SpaceRole",
    "SpaceType",
    "Transaction",
    "TransactionType",
]
