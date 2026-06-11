"""Investment accounts, holdings, prices and snapshots.

Implements INV-01..INV-06, PAT-01. Crypto quantities use NUMERIC(28,10)
(INV-01); money stays NUMERIC(14,2) (GLO-01).
"""

import datetime as dt
import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import AuditMixin


class AccountKind(enum.StrEnum):
    crypto = "crypto"
    stocks = "stocks"
    fixed_income = "fixed_income"
    other = "other"


class MovementType(enum.StrEnum):
    buy = "buy"
    sell = "sell"
    deposit = "deposit"
    withdraw = "withdraw"


class InvestmentAccount(Base, AuditMixin):
    __tablename__ = "investment_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[AccountKind] = mapped_column(
        Enum(AccountKind, name="account_kind", native_enum=False, length=15), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    holdings: Mapped[list["Holding"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Holding(Base, AuditMixin):
    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("account_id", "asset_symbol", name="uq_holding_symbol"),
        CheckConstraint("quantity >= 0", name="ck_holding_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("investment_accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Crypto: CoinGecko id (p. ej. "bitcoin"); stocks: ticker.
    asset_symbol: Mapped[str] = mapped_column(String(60), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)  # INV-01
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    # INV-06: realized P&L accumulates from sells.
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )

    account: Mapped[InvestmentAccount] = relationship(back_populates="holdings")
    movements: Mapped[list["InvestmentMovement"]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )


class InvestmentMovement(Base, AuditMixin):
    """INV-02: quantities change only through movements, never direct edits."""

    __tablename__ = "investment_movements"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_movement_quantity"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    holding_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, name="movement_type", native_enum=False, length=10), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    holding: Mapped[Holding] = relationship(back_populates="movements")


class AssetPrice(Base):
    """INV-03/INV-04: server-side price cache (CoinGecko) and manual prices."""

    __tablename__ = "asset_prices"

    symbol: Mapped[str] = mapped_column(String(60), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="coingecko")


class PortfolioSnapshot(Base):
    """INV-05: daily valuation persisted; charts never recompute history."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("space_id", "date", name="uq_portfolio_snapshot"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # INV-03b: backfilled points never overwrite real snapshots.
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="snapshot")


class NetWorthSnapshot(Base):
    """PAT-01: activos (portafolios) − pasivos (deuda TDC) por día."""

    __tablename__ = "net_worth_snapshots"
    __table_args__ = (UniqueConstraint("space_id", "date", name="uq_networth_snapshot"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    assets: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    liabilities: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    net_worth: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
