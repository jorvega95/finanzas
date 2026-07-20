"""Inversiones y patrimonio neto. Implementa INV-01..INV-06, PAT-01/PAT-02.

INV-02: las cantidades solo cambian por movimientos. FX-04: la valuación usa
la tasa del día (mark-to-market), nunca tasas congeladas.
"""

import datetime as dt
import uuid
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dates import today_in_tz
from app.models.investments import (
    AccountKind,
    Holding,
    InvestmentAccount,
    InvestmentMovement,
    MovementType,
    NetWorthSnapshot,
    PortfolioSnapshot,
)
from app.models.spaces import Space
from app.services import fx, prices

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_EVEN)


async def get_account(
    session: AsyncSession, space_id: uuid.UUID, account_id: uuid.UUID
) -> InvestmentAccount:
    account = await session.get(
        InvestmentAccount, account_id, options=[selectinload(InvestmentAccount.holdings)]
    )
    if account is None or account.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    return account


async def space_holds_symbol(session: AsyncSession, space_id: uuid.UUID, symbol: str) -> bool:
    """INV-04: ¿el espacio tiene algún holding (qty > 0) con este símbolo?

    Predicado para autorizar la captura de un precio manual: solo se permite
    sobre instrumentos que el espacio efectivamente posee.
    """
    found = await session.scalar(
        select(Holding.id)
        .join(InvestmentAccount, Holding.account_id == InvestmentAccount.id)
        .where(
            InvestmentAccount.space_id == space_id,
            Holding.asset_symbol == symbol,
            Holding.quantity > 0,
        )
        .limit(1)
    )
    return found is not None


async def create_account(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    name: str,
    kind: AccountKind,
) -> InvestmentAccount:
    account = InvestmentAccount(space_id=space.id, name=name, kind=kind, created_by=created_by)
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def register_movement(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    account_id: uuid.UUID,
    *,
    type: MovementType,
    asset_symbol: str,
    quantity: Decimal,
    price: Decimal | None,
    date: dt.date,
    asset_name: str = "",
    currency: str = "USD",
) -> Holding:
    """INV-02: buy/sell/deposit/withdraw; nunca edición directa de cantidades.

    buy: avg = (q_old·avg_old + q_in·precio) / q_new.
    sell: cantidad baja, avg NO cambia; P&L realizado = q·(precio − avg).
    deposit con precio actualiza avg ponderado; withdraw solo resta.
    """
    if quantity <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cantidad inválida")
    account = await get_account(session, space.id, account_id)

    holding = next((h for h in account.holdings if h.asset_symbol == asset_symbol), None)
    if holding is None:
        if type in (MovementType.sell, MovementType.withdraw):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No tienes posición")
        if price is None and type == MovementType.buy:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "buy requiere precio")
        holding = Holding(
            account_id=account.id,
            asset_symbol=asset_symbol,
            asset_name=asset_name or asset_symbol,
            quantity=Decimal("0"),
            avg_cost=price or Decimal("0"),
            currency=currency,
            created_by=created_by,
        )
        session.add(holding)
        await session.flush()

    realized: Decimal | None = None
    if type in (MovementType.buy, MovementType.deposit):
        if type == MovementType.buy and price is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "buy requiere precio")
        new_quantity = holding.quantity + quantity
        if price is not None and new_quantity > 0:
            holding.avg_cost = (
                holding.quantity * holding.avg_cost + quantity * price
            ) / new_quantity
        holding.quantity = new_quantity
    else:  # sell | withdraw
        if quantity > holding.quantity:
            # INV-02: sell con qty > posición se rechaza.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Cantidad mayor a tu posición"
            )
        if type == MovementType.sell:
            if price is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "sell requiere precio")
            realized = money(quantity * (price - holding.avg_cost))
            holding.realized_pnl = holding.realized_pnl + realized
        holding.quantity = holding.quantity - quantity
        # INV-02: el costo promedio NO cambia al vender.

    session.add(
        InvestmentMovement(
            holding_id=holding.id,
            type=type,
            date=date,
            quantity=quantity,
            price=price,
            realized_pnl=realized,
            created_by=created_by,
        )
    )
    await session.commit()
    await session.refresh(holding)
    return holding


async def portfolio_valuation(
    session: AsyncSession, space: Space, provider: prices.PriceProvider | None = None
) -> dict[str, Any]:
    """INV-06 + FX-04: valor actual y P&L por holding, convertido a la moneda
    base con la tasa DEL DÍA (mark-to-market)."""
    today = today_in_tz(space.timezone)
    accounts = (
        (
            await session.execute(
                select(InvestmentAccount)
                .options(selectinload(InvestmentAccount.holdings))
                .where(InvestmentAccount.space_id == space.id)
            )
        )
        .scalars()
        .all()
    )
    symbols = sorted({h.asset_symbol for a in accounts for h in a.holdings if h.quantity > 0})
    price_map = await prices.get_prices(session, space.id, symbols, provider)

    holdings_out: list[dict[str, Any]] = []
    total = ZERO
    total_unrealized = ZERO
    total_realized = ZERO
    for account in accounts:
        for holding in account.holdings:
            total_realized += holding.realized_pnl
            if holding.quantity <= 0:
                continue
            price_row = price_map.get(holding.asset_symbol)
            price = price_row.price if price_row else None
            price_currency = price_row.currency if price_row else holding.currency
            value_base: Decimal | None = None
            unrealized: Decimal | None = None
            if price is not None:
                rate = await fx.get_rate(session, price_currency, space.base_currency, today)
                if rate is not None:
                    value_base = money(holding.quantity * price * rate)
                    cost_rate = await fx.get_rate(
                        session, holding.currency, space.base_currency, today
                    )
                    cost_base = (
                        money(holding.quantity * holding.avg_cost * cost_rate)
                        if cost_rate is not None
                        else None
                    )
                    unrealized = value_base - cost_base if cost_base is not None else None
            if value_base is not None:
                total += value_base
            if unrealized is not None:
                total_unrealized += unrealized
            holdings_out.append(
                {
                    "holding_id": holding.id,
                    "account_id": account.id,
                    "account_name": account.name,
                    "kind": account.kind.value,
                    "asset_symbol": holding.asset_symbol,
                    "asset_name": holding.asset_name,
                    "quantity": holding.quantity,
                    "avg_cost": holding.avg_cost,
                    "currency": holding.currency,
                    "price": price,
                    "price_fetched_at": price_row.fetched_at if price_row else None,
                    "price_source": price_row.source if price_row else None,
                    "value_base": value_base,
                    "unrealized_pnl": unrealized,
                    "realized_pnl": holding.realized_pnl,
                }
            )
    return {
        "total_value": total,
        "total_unrealized_pnl": total_unrealized,
        "total_realized_pnl": total_realized,
        "holdings": holdings_out,
    }


async def snapshot_portfolio(
    session: AsyncSession, space: Space, provider: prices.PriceProvider | None = None
) -> PortfolioSnapshot:
    """INV-05: persiste la valuación del día (idempotente por espacio+fecha);
    las gráficas históricas leen SOLO snapshots, nunca recalculan."""
    today = today_in_tz(space.timezone)
    valuation = await portfolio_valuation(session, space, provider)
    breakdown = {
        h["asset_symbol"]: {
            "quantity": str(h["quantity"]),
            "price": str(h["price"]) if h["price"] is not None else None,
            "value_base": str(h["value_base"]) if h["value_base"] is not None else None,
        }
        for h in valuation["holdings"]
    }
    existing = await session.scalar(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.space_id == space.id, PortfolioSnapshot.date == today
        )
    )
    if existing is not None:
        existing.total_value = valuation["total_value"]
        existing.breakdown = breakdown
        snapshot = existing
    else:
        snapshot = PortfolioSnapshot(
            space_id=space.id,
            date=today,
            total_value=valuation["total_value"],
            breakdown=breakdown,
        )
        session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return snapshot


async def snapshot_net_worth(session: AsyncSession, space: Space) -> NetWorthSnapshot:
    """PAT-01/PAT-02: activos = portafolio + saldos de tarjetas no-crédito
    (TAR-05); pasivos = deuda de tarjetas de crédito (TDC-09 a+b+c). Idempotente
    por día."""
    from app.models.cards import Card
    from app.models.catalogs import CardBehavior, CardType
    from app.services.cards import card_balance, debt_summary

    today = today_in_tz(space.timezone)
    portfolio = await session.scalar(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.space_id == space.id, PortfolioSnapshot.date == today
        )
    )
    portfolio_value = portfolio.total_value if portfolio is not None else ZERO

    cards = (
        await session.execute(
            select(Card, CardType.behavior)
            .join(CardType, Card.card_type_id == CardType.id)
            .where(Card.space_id == space.id)
        )
    ).all()
    liabilities = ZERO
    card_balances = ZERO
    for card, behavior in cards:
        if behavior == CardBehavior.credit:
            debt = await debt_summary(session, card)
            liabilities += debt["total_debt"]
        else:
            card_balances += await card_balance(session, card)  # TAR-05

    assets = portfolio_value + card_balances

    existing = await session.scalar(
        select(NetWorthSnapshot).where(
            NetWorthSnapshot.space_id == space.id, NetWorthSnapshot.date == today
        )
    )
    breakdown = {
        "portfolio": str(portfolio_value),
        "card_balances": str(card_balances),
        "card_debt": str(liabilities),
    }
    if existing is not None:
        existing.assets = assets
        existing.liabilities = liabilities
        existing.net_worth = assets - liabilities
        existing.breakdown = breakdown
        snapshot = existing
    else:
        snapshot = NetWorthSnapshot(
            space_id=space.id,
            date=today,
            assets=assets,
            liabilities=liabilities,
            net_worth=assets - liabilities,
            breakdown=breakdown,
        )
        session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return snapshot
