"""Import every model here so Alembic autogenerate sees the full metadata."""

from app.db.base import Base
from app.models.budgets import Budget
from app.models.cards import Card, CardLayout, CardStatement, CutoffDayPolicy, StatementStatus
from app.models.catalogs import (
    CardBehavior,
    CardType,
    Category,
    CategoryKind,
    ExpenseNature,
    PaymentMethod,
    PaymentMethodType,
)
from app.models.fx import ExchangeRate
from app.models.imports import ImportBatch, ImportStatus
from app.models.investments import (
    AccountKind,
    AssetPrice,
    Holding,
    InvestmentAccount,
    InvestmentMovement,
    ManualAssetPrice,
    MovementType,
    NetWorthSnapshot,
    PortfolioSnapshot,
)
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus, PlanStatus
from app.models.recurring import RecurringFrequency, RecurringRule, RecurringTombstone
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Profile, Space, SpaceInvite, SpaceMember, SpaceRole, SpaceType
from app.models.transactions import Transaction, TransactionType

__all__ = [
    "AccountKind",
    "AssetPrice",
    "Base",
    "Budget",
    "Card",
    "CardBehavior",
    "CardLayout",
    "CardStatement",
    "CardType",
    "Holding",
    "ImportBatch",
    "ImportStatus",
    "InvestmentAccount",
    "InvestmentMovement",
    "ManualAssetPrice",
    "MovementType",
    "NetWorthSnapshot",
    "PortfolioSnapshot",
    "Category",
    "CategoryKind",
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
    "SpaceInvite",
    "SpaceMember",
    "SpaceRole",
    "SpaceType",
    "StatementStatus",
    "Transaction",
    "TransactionType",
]
