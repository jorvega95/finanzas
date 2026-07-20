"""Router: investments + net worth. Implements INV-01..06, PAT-01/02."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.investments import InvestmentAccount, NetWorthSnapshot, PortfolioSnapshot
from app.schemas.investments import (
    AccountCreate,
    AccountOut,
    ManualPrice,
    MovementCreate,
    NetWorthOut,
    PortfolioOut,
    SnapshotOut,
)
from app.services import investments as svc
from app.services import prices

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(db: DbSession, space_and_member: ActiveSpace) -> list[InvestmentAccount]:
    space, _ = space_and_member
    rows = await db.execute(
        select(InvestmentAccount)
        .where(InvestmentAccount.space_id == space.id)
        .order_by(InvestmentAccount.name)
    )
    return list(rows.scalars().all())


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: AccountCreate
) -> InvestmentAccount:
    space, _ = space_and_member
    return await svc.create_account(db, space, user.id, name=payload.name, kind=payload.kind)


@router.post(
    "/accounts/{account_id}/movements",
    response_model=PortfolioOut,
    status_code=status.HTTP_201_CREATED,
)
async def register_movement(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    account_id: uuid.UUID,
    payload: MovementCreate,
) -> PortfolioOut:
    """INV-02: alta por operaciones; responde con el portafolio actualizado."""
    space, _ = space_and_member
    await svc.register_movement(
        db,
        space,
        user.id,
        account_id,
        type=payload.type,
        asset_symbol=payload.asset_symbol,
        asset_name=payload.asset_name,
        quantity=payload.quantity,
        price=payload.price,
        date=payload.date,
        currency=payload.currency,
    )
    return PortfolioOut(**(await svc.portfolio_valuation(db, space)))


@router.get("/portfolio", response_model=PortfolioOut)
async def portfolio(db: DbSession, space_and_member: ActiveSpace) -> PortfolioOut:
    """INV-06: valor actual, P&L realizado y no realizado (FX-04 hoy)."""
    space, _ = space_and_member
    return PortfolioOut(**(await svc.portfolio_valuation(db, space)))


@router.post("/prices", response_model=dict)
async def manual_price(
    db: DbSession, space_and_member: EditorSpace, payload: ManualPrice
) -> dict[str, str]:
    """INV-04: captura manual de precio para activos no-crypto, por espacio."""
    space, _ = space_and_member
    # INV-04: solo se puede fijar precio de símbolos que el espacio posee.
    if not await svc.space_holds_symbol(db, space.id, payload.symbol):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No tienes ninguna posición con ese símbolo",
        )
    row = await prices.set_manual_price(
        db, space.id, payload.symbol, payload.price, payload.currency
    )
    await db.commit()
    return {"symbol": row.symbol, "price": str(row.price), "currency": row.currency}


@router.post("/snapshot", response_model=SnapshotOut)
async def snapshot_now(db: DbSession, space_and_member: EditorSpace) -> SnapshotOut:
    """INV-05: snapshot manual (el job diario hace lo mismo). Idempotente."""
    space, _ = space_and_member
    snapshot = await svc.snapshot_portfolio(db, space)
    return SnapshotOut.model_validate(snapshot)


@router.get("/snapshots", response_model=list[SnapshotOut])
async def snapshots(
    db: DbSession, space_and_member: ActiveSpace, limit: int = 90
) -> list[PortfolioSnapshot]:
    space, _ = space_and_member
    rows = await db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.space_id == space.id)
        .order_by(PortfolioSnapshot.date.desc())
        .limit(min(limit, 365))
    )
    return list(reversed(rows.scalars().all()))


@router.post("/net-worth/snapshot", response_model=NetWorthOut)
async def net_worth_snapshot(db: DbSession, space_and_member: EditorSpace) -> NetWorthOut:
    """PAT-01: persiste activos − deuda TDC del día (idempotente)."""
    space, _ = space_and_member
    snapshot = await svc.snapshot_net_worth(db, space)
    return NetWorthOut.model_validate(snapshot)


@router.get("/net-worth", response_model=list[NetWorthOut])
async def net_worth_history(
    db: DbSession, space_and_member: ActiveSpace, limit: int = 90
) -> list[NetWorthSnapshot]:
    space, _ = space_and_member
    rows = await db.execute(
        select(NetWorthSnapshot)
        .where(NetWorthSnapshot.space_id == space.id)
        .order_by(NetWorthSnapshot.date.desc())
        .limit(min(limit, 365))
    )
    return list(reversed(rows.scalars().all()))
