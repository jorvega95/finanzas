"""Events. Implements EVT-01..EVT-03 (EVT-04 lives in the shared DSH-03
predicates of services/dashboard.py).

GLO-01: Decimal everywhere. GLO-05: space-scoped. Aggregates in SQL (DSH-03).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.dates import today_in_tz
from app.core.text import normalize_name
from app.models.accounts import Account
from app.models.catalogs import AccountBehavior, AccountType
from app.models.events import Event
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services.dashboard import AMOUNT_BASE, ZERO, _roll_up_to_root, _space_categories, to_money


async def get_event(session: AsyncSession, space_id: uuid.UUID, event_id: uuid.UUID) -> Event:
    event = await session.get(Event, event_id)
    if event is None or event.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evento no encontrado")  # GLO-05
    return event


async def validate_event_link(
    session: AsyncSession,
    space_id: uuid.UUID,
    event_id: uuid.UUID | None,
    current_event_id: uuid.UUID | None = None,
) -> None:
    """EVT-02: the event must be in the active space; an inactive event accepts
    no new links (EVT-01/CAT-04), but an existing link may be kept on edit."""
    if event_id is None:
        return
    event = await session.get(Event, event_id)
    if event is None or event.space_id != space_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El evento no existe")
    if not event.is_active and event_id != current_event_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"El evento {event.name} está inactivo; reactívalo para ligarle movimientos",
        )


async def _unique_name(
    session: AsyncSession, space_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> str:
    """EVT-01: name unique per space (CAT-01 style)."""
    normalized = normalize_name(name)
    stmt = select(Event.id).where(Event.space_id == space_id, Event.name_normalized == normalized)
    if exclude_id is not None:
        stmt = stmt.where(Event.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un evento con ese nombre")
    return normalized


async def list_events(
    session: AsyncSession, space_id: uuid.UUID, include_inactive: bool = False
) -> list[Event]:
    stmt = select(Event).where(Event.space_id == space_id)
    if not include_inactive:
        stmt = stmt.where(Event.is_active.is_(True))
    rows = await session.execute(
        stmt.order_by(Event.date.desc().nulls_last(), Event.name_normalized)
    )
    return list(rows.scalars().all())


async def create_event(
    session: AsyncSession, space: Space, created_by: uuid.UUID, changes: dict[str, Any]
) -> Event:
    name = str(changes["name"])
    event = Event(
        space_id=space.id,
        name=name,
        name_normalized=await _unique_name(session, space.id, name),
        date=changes.get("date"),
        budget=changes.get("budget"),
        notes=changes.get("notes"),
        created_by=created_by,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def update_event(session: AsyncSession, event: Event, changes: dict[str, Any]) -> Event:
    if "name" in changes:
        event.name_normalized = await _unique_name(
            session, event.space_id, str(changes["name"]), exclude_id=event.id
        )
    for field in ("name", "date", "budget", "notes", "is_active"):
        if field in changes:
            setattr(event, field, changes[field])
    await session.commit()
    await session.refresh(event)
    return event


async def delete_event(session: AsyncSession, event: Event) -> None:
    """GLO-03: physical delete only without linked movements; otherwise 409 so
    the client deactivates it."""
    from app.models.commitments import Commitment

    linked = await session.scalar(
        select(Transaction.id).where(Transaction.event_id == event.id).limit(1)
    )
    if linked is None:
        linked = await session.scalar(
            select(Commitment.id).where(Commitment.event_id == event.id).limit(1)
        )
    if linked is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El evento tiene movimientos o compromisos ligados; desactívalo en lugar de eliminarlo",
        )
    await session.delete(event)
    await session.commit()


@dataclass
class EventLoan:
    account_id: uuid.UUID
    name: str
    currency: str
    balance: Decimal


async def event_summary(session: AsyncSession, space: Space, event: Event) -> dict[str, Any]:
    """EVT-03: total cost of the event, in base currency with frozen rates.

    spent    = Σ linked expenses (MSI parents excluded, MSI-03) + Σ ALL the
               installments (any status but canceled) of linked MSI parents —
               it's the event's whole cost, not a month's, and by MSI-02 it
               equals the parent amount without counting it twice. An early
               settlement (MSI-07) is its own expense, linked like its parent.
    received = Σ linked incomes (cash gifts).
    net      = spent − received.
    """
    from app.services import fx
    from app.services.accounts import account_balance
    from app.services.commitments import list_commitments

    linked = [Transaction.space_id == space.id, Transaction.event_id == event.id]
    direct_rows = (
        await session.execute(
            select(Transaction.category_id, func.sum(AMOUNT_BASE))
            .where(
                *linked,
                Transaction.type == TransactionType.expense,
                Transaction.installment_plan_id.is_(None),
            )
            .group_by(Transaction.category_id)
        )
    ).all()
    parent = aliased(Transaction)
    msi_rows = (
        await session.execute(
            select(
                parent.category_id,
                func.sum(Installment.amount * func.coalesce(parent.fx_rate_to_base, 1)),
            )
            .select_from(Installment)
            .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
            .join(parent, InstallmentPlan.transaction_id == parent.id)
            .where(
                InstallmentPlan.space_id == space.id,
                parent.event_id == event.id,
                Installment.status != InstallmentStatus.canceled,
            )
            .group_by(parent.category_id)
        )
    ).all()
    received = await session.scalar(
        select(func.coalesce(func.sum(AMOUNT_BASE), 0)).where(
            *linked, Transaction.type == TransactionType.income
        )
    )
    movements = await session.scalar(select(func.count()).select_from(Transaction).where(*linked))

    categories = await _space_categories(session, space.id)
    by_category = _roll_up_to_root(categories, list(direct_rows) + list(msi_rows))
    spent = sum((row["total"] for row in by_category), ZERO)
    received_total = to_money(received)

    # Loans (TAR-11) with movements linked to the event, with their balance today.
    loan_accounts = (
        (
            await session.execute(
                select(Account)
                .join(AccountType, Account.account_type_id == AccountType.id)
                .where(
                    Account.space_id == space.id,
                    AccountType.behavior == AccountBehavior.loan,
                    select(Transaction.id)
                    .where(
                        *linked,
                        or_(
                            Transaction.account_id == Account.id,
                            Transaction.account_to_id == Account.id,
                        ),
                    )
                    .exists(),
                )
                .order_by(Account.name_normalized)
            )
        )
        .scalars()
        .all()
    )
    loans = [
        EventLoan(
            account_id=account.id,
            name=account.name,
            currency=account.currency,
            balance=await account_balance(session, account),
        )
        for account in loan_accounts
    ]

    # CXP-03: what is still owed to its vendors, in base at today's rate (it
    # is a future payment, like PRO-06; amounts in base pass through).
    today = today_in_tz(space.timezone)
    pending_commitments = ZERO
    for state in await list_commitments(session, space, event_id=event.id):
        valued = await fx.mark_to_market(
            session, state.pending, state.commitment.currency, space.base_currency, today
        )
        pending_commitments += valued if valued is not None else ZERO

    return {
        "pending_commitments": to_money(pending_commitments),
        "spent": spent,
        "received": received_total,
        "net": spent - received_total,
        "budget_remaining": event.budget - spent if event.budget is not None else None,
        "movements": movements or 0,
        "by_category": by_category,
        "loans": loans,
    }
