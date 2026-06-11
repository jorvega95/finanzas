"""Import every model here so Alembic autogenerate sees the full metadata."""

from app.db.base import Base
from app.models.budgets import Budget
from app.models.cards import CardStatement, CreditCard, CutoffDayPolicy, StatementStatus
from app.models.catalogs import (
    Category,
    CategoryKind,
    ExpenseNature,
    PaymentMethod,
    PaymentMethodType,
)
from app.models.fx import ExchangeRate
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus, PlanStatus
from app.models.recurring import RecurringFrequency, RecurringRule, RecurringTombstone
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Profile, Space, SpaceMember, SpaceRole, SpaceType
from app.models.transactions import Transaction, TransactionType

__all__ = [
    "Base",
    "Budget",
    "CardStatement",
    "Category",
    "CategoryKind",
    "CreditCard",
    "CutoffDayPolicy",
    "ExchangeRate",
    "ExpenseNature",
    "Installment",
    "InstallmentPlan",
    "InstallmentStatus",
    "PaymentMethod",
    "PaymentMethodType",
    "PlanStatus",
    "Profile",
    "RecurringFrequency",
    "RecurringRule",
    "RecurringTombstone",
    "Reminder",
    "ReminderChannel",
    "ReminderKind",
    "ReminderStatus",
    "Space",
    "SpaceMember",
    "SpaceRole",
    "SpaceType",
    "StatementStatus",
    "Transaction",
    "TransactionType",
]
