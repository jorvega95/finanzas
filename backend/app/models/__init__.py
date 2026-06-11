"""Import every model here so Alembic autogenerate sees the full metadata."""

from app.db.base import Base
from app.models.catalogs import (
    Category,
    CategoryKind,
    ExpenseNature,
    PaymentMethod,
    PaymentMethodType,
)
from app.models.spaces import Profile, Space, SpaceMember, SpaceRole, SpaceType

__all__ = [
    "Base",
    "Category",
    "CategoryKind",
    "ExpenseNature",
    "PaymentMethod",
    "PaymentMethodType",
    "Profile",
    "Space",
    "SpaceMember",
    "SpaceRole",
    "SpaceType",
]
