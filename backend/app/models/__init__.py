"""Import every model here so Alembic autogenerate sees the full metadata."""

from app.db.base import Base
from app.models.accounts import (
    Account,
    AccountLayout,
    CutoffDayPolicy,
    Statement,
    StatementStatus,
)
from app.models.billing import (
    BillingClient,
    BillingSettings,
    FilingKind,
    Invoice,
    InvoiceablePayment,
    StoredFile,
    TaxFiling,
)
from app.models.budgets import Budget
from app.models.catalogs import (
    AccountBehavior,
    AccountType,
    Category,
    CategoryKind,
    ExpenseNature,
)
from app.models.commitments import Commitment, CommitmentPayment
from app.models.events import Event
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
from app.models.recurring import (
    RecurringFrequency,
    RecurringKind,
    RecurringRule,
    RecurringTombstone,
)
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Profile, Space, SpaceInvite, SpaceMember, SpaceRole, SpaceType
from app.models.transactions import Transaction, TransactionType

__all__ = [
    "Account",
    "AccountBehavior",
    "AccountKind",
    "AccountLayout",
    "AccountType",
    "AssetPrice",
    "Base",
    "BillingClient",
    "BillingSettings",
    "Budget",
    "Holding",
    "ImportBatch",
    "ImportStatus",
    "Invoice",
    "InvoiceablePayment",
    "InvestmentAccount",
    "InvestmentMovement",
    "ManualAssetPrice",
    "MovementType",
    "NetWorthSnapshot",
    "PortfolioSnapshot",
    "Category",
    "CategoryKind",
    "Commitment",
    "CommitmentPayment",
    "Event",
    "CutoffDayPolicy",
    "ExchangeRate",
    "ExpenseNature",
    "FilingKind",
    "Installment",
    "InstallmentPlan",
    "InstallmentStatus",
    "PlanStatus",
    "Profile",
    "RecurringFrequency",
    "RecurringKind",
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
    "Statement",
    "StatementStatus",
    "StoredFile",
    "TaxFiling",
    "Transaction",
    "TransactionType",
]
