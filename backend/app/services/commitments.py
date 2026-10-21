"""Commitments with vendors. Implements CXP-01..CXP-08.

paid    = paid_before_tracking + Σ amount of the expenses linked by
          commitment_id (an MSI parent counts in full: the vendor was paid).
pending = total_amount − paid. Computed in SQL (DSH-03), never stored.
The schedule (CXP-02) is covered FIFO by date with the tracked payments.

GLO-01: Decimal everywhere. GLO-02: pure dates. GLO-05: space-scoped.
"""

import datetime as dt
import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dates import today_in_tz
from app.core.text import normalize_name
from app.models.catalogs import BALANCE_BEHAVIORS, Category, CategoryKind
from app.models.commitments import Commitment, CommitmentPayment
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType

ZERO = Decimal("0.00")
GIFTS_CATEGORY_NAME = "Regalos recibidos"  # CAT-02
REMINDER_OFFSETS = (3, 1)  # CXP-08, like REM-01's default
REMINDER_CHANNELS = (
    ReminderChannel.in_app,
    ReminderChannel.email,
    ReminderChannel.desktop,
)  # REM-08
SUPPORTED_CURRENCIES = {"MXN", "USD"}  # TXN-04


def _reject(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


# --- Computed state (CXP-02/03/05) -----------------------------------------------------


@dataclass
class ScheduleRow:
    id: uuid.UUID
    due_date: dt.date
    amount: Decimal
    covered: Decimal
    uncovered: Decimal
    is_covered: bool
    is_overdue: bool


@dataclass
class CommitmentState:
    commitment: Commitment
    paid: Decimal
    pending: Decimal
    status: str  # pending | paid | canceled
    is_overdue: bool
    abonos: int
    schedule: list[ScheduleRow] = field(default_factory=list)
    # CXP-07: pending not covered by any schedule row (dated `due_date`, if any).
    unscheduled_pending: Decimal = ZERO


async def tracked_payments(
    session: AsyncSession,
    commitment_ids: Collection[uuid.UUID],
    exclude_txn_ids: Collection[uuid.UUID] = (),
) -> dict[uuid.UUID, tuple[Decimal, int]]:
    """CXP-03: {commitment id: (Σ linked expenses, count)}, in one SQL query."""
    if not commitment_ids:
        return {}
    stmt = (
        select(
            Transaction.commitment_id,
            func.coalesce(func.sum(Transaction.amount), 0),
            func.count(Transaction.id),
        )
        .where(
            Transaction.commitment_id.in_(list(commitment_ids)),
            Transaction.type == TransactionType.expense,
        )
        .group_by(Transaction.commitment_id)
    )
    if exclude_txn_ids:
        stmt = stmt.where(Transaction.id.not_in(list(exclude_txn_ids)))
    rows = (await session.execute(stmt)).all()
    return {cid: (Decimal(total), int(count)) for cid, total, count in rows if cid is not None}


def compute_state(
    commitment: Commitment, tracked: Decimal, abonos: int, today: dt.date
) -> CommitmentState:
    """CXP-02/05: coverage FIFO by date, status and overdue flag."""
    paid = commitment.paid_before_tracking + tracked
    pending = commitment.total_amount - paid
    remaining = tracked
    rows: list[ScheduleRow] = []
    for payment in sorted(commitment.payments, key=lambda p: (p.due_date, p.created_at)):
        covered = min(payment.amount, max(remaining, ZERO))
        remaining -= covered
        uncovered = payment.amount - covered
        rows.append(
            ScheduleRow(
                id=payment.id,
                due_date=payment.due_date,
                amount=payment.amount,
                covered=covered,
                uncovered=uncovered,
                is_covered=uncovered == ZERO,
                is_overdue=uncovered > ZERO and payment.due_date < today,
            )
        )
    unscheduled = max(pending - sum((r.uncovered for r in rows), ZERO), ZERO)
    if commitment.is_canceled:
        state, overdue = "canceled", False
    elif pending <= ZERO:
        state, overdue = "paid", False
    else:
        state = "pending"
        overdue = any(r.is_overdue for r in rows) or (
            unscheduled > ZERO and commitment.due_date is not None and commitment.due_date < today
        )
    return CommitmentState(
        commitment=commitment,
        paid=paid,
        pending=pending,
        status=state,
        is_overdue=overdue,
        abonos=abonos,
        schedule=rows,
        unscheduled_pending=unscheduled if state == "pending" else ZERO,
    )


async def states_for(
    session: AsyncSession, space: Space, commitments: Iterable[Commitment]
) -> list[CommitmentState]:
    items = list(commitments)
    tracked = await tracked_payments(session, [c.id for c in items])
    today = today_in_tz(space.timezone)
    return [compute_state(c, *tracked.get(c.id, (ZERO, 0)), today=today) for c in items]


async def list_commitments(
    session: AsyncSession,
    space: Space,
    *,
    include_closed: bool = False,
    event_id: uuid.UUID | None = None,
) -> list[CommitmentState]:
    """CXP-05: paid and canceled commitments are hidden unless include_closed."""
    stmt = (
        select(Commitment)
        .options(selectinload(Commitment.payments))
        .where(Commitment.space_id == space.id)
    )
    if event_id is not None:
        stmt = stmt.where(Commitment.event_id == event_id)
    rows = (await session.execute(stmt.order_by(Commitment.created_at))).scalars().all()
    states = await states_for(session, space, rows)
    if not include_closed:
        states = [s for s in states if s.status == "pending"]
    return sorted(
        states,
        key=lambda s: (
            s.status != "pending",
            _next_due(s) or dt.date.max,
            normalize_name(s.commitment.name),
        ),
    )


def _next_due(state: CommitmentState) -> dt.date | None:
    dates = [r.due_date for r in state.schedule if not r.is_covered]
    if state.unscheduled_pending > ZERO and state.commitment.due_date is not None:
        dates.append(state.commitment.due_date)
    return min(dates) if dates else None


async def get_commitment(
    session: AsyncSession, space_id: uuid.UUID, commitment_id: uuid.UUID
) -> Commitment:
    commitment: Commitment | None = await session.scalar(
        select(Commitment)
        .options(selectinload(Commitment.payments))
        .where(Commitment.id == commitment_id)
    )
    if commitment is None or commitment.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compromiso no encontrado")  # GLO-05
    return commitment


async def commitment_state(
    session: AsyncSession, space: Space, commitment: Commitment
) -> CommitmentState:
    return (await states_for(session, space, [commitment]))[0]


# --- CRUD (CXP-01/02/06) --------------------------------------------------------------


async def _validate_refs(
    session: AsyncSession,
    space_id: uuid.UUID,
    changes: dict[str, Any],
    current_event_id: uuid.UUID | None = None,
) -> None:
    from app.services.events import validate_event_link

    if "event_id" in changes:
        await validate_event_link(session, space_id, changes["event_id"], current_event_id)
    category_id = changes.get("category_id")
    if category_id is not None:
        category = await session.get(Category, category_id)
        if category is None or category.space_id != space_id:
            raise _reject("La categoría no existe")
        if category.kind != CategoryKind.expense:
            raise _reject("La categoría de los abonos debe ser de gasto")
    if "currency" in changes and changes["currency"] not in SUPPORTED_CURRENCIES:
        raise _reject(f"Moneda no soportada: {changes['currency']}")


def _validate_schedule(
    total: Decimal, paid_before: Decimal, schedule: list[dict[str, Any]] | None
) -> None:
    """CXP-01/02: paid_before ≤ total; Σ schedule ≤ total − paid_before."""
    if paid_before > total:
        raise _reject("Lo abonado antes no puede ser mayor al total pactado")
    if schedule:
        scheduled = sum((Decimal(row["amount"]) for row in schedule), ZERO)
        if scheduled > total - paid_before:
            raise _reject(
                f"El calendario suma {scheduled} y solo quedan "
                f"{total - paid_before} por pagar; ajusta los montos"
            )


async def create_commitment(
    session: AsyncSession, space: Space, created_by: uuid.UUID, data: dict[str, Any]
) -> Commitment:
    await _validate_refs(session, space.id, data)
    paid_before = data.get("paid_before_tracking") or ZERO
    schedule = data.get("schedule") or []
    _validate_schedule(data["total_amount"], paid_before, schedule)
    commitment = Commitment(
        space_id=space.id,
        name=data["name"],
        total_amount=data["total_amount"],
        currency=data["currency"],
        event_id=data.get("event_id"),
        category_id=data.get("category_id"),
        paid_before_tracking=paid_before,
        due_date=data.get("due_date"),
        notes=data.get("notes"),
        created_by=created_by,
        payments=[CommitmentPayment(due_date=r["due_date"], amount=r["amount"]) for r in schedule],
    )
    session.add(commitment)
    await session.flush()
    await sync_reminders(session, space, [commitment.id])
    await session.commit()
    return await get_commitment(session, space.id, commitment.id)


async def update_commitment(
    session: AsyncSession, space: Space, commitment: Commitment, changes: dict[str, Any]
) -> Commitment:
    """CXP-06: total/paid_before editable while pending ≥ 0; currency locked
    once there are abonos; the schedule, when sent, is replaced as a whole."""
    await _validate_refs(session, space.id, changes, current_event_id=commitment.event_id)
    tracked, abonos = (await tracked_payments(session, [commitment.id])).get(
        commitment.id, (ZERO, 0)
    )
    if "currency" in changes and changes["currency"] != commitment.currency and abonos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El compromiso ya tiene abonos; no se puede cambiar su moneda",
        )
    if "event_id" in changes and changes["event_id"] != commitment.event_id and abonos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El compromiso ya tiene abonos; cambia el evento desde cada abono o crea otro",
        )
    total = changes.get("total_amount") or commitment.total_amount
    paid_before = (
        changes["paid_before_tracking"]
        if changes.get("paid_before_tracking") is not None
        else commitment.paid_before_tracking
    )
    if total - paid_before - tracked < ZERO:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Ya se abonaron {paid_before + tracked}; el total no puede ser menor",
        )
    schedule = changes.pop("schedule", None)
    _validate_schedule(
        total,
        paid_before,
        schedule if schedule is not None else [{"amount": p.amount} for p in commitment.payments],
    )
    for name in (
        "name",
        "total_amount",
        "currency",
        "event_id",
        "category_id",
        "paid_before_tracking",
        "due_date",
        "notes",
        "is_canceled",
    ):
        # Required amounts sent as null are ignored rather than cleared.
        required = name in ("total_amount", "paid_before_tracking", "currency", "name")
        if name in changes and not (required and changes[name] is None):
            setattr(commitment, name, changes[name])
    if schedule is not None:
        commitment.payments = [
            CommitmentPayment(due_date=r["due_date"], amount=r["amount"]) for r in schedule
        ]
    await session.flush()
    await sync_reminders(session, space, [commitment.id])
    await session.commit()
    return await get_commitment(session, space.id, commitment.id)


async def delete_commitment(session: AsyncSession, space: Space, commitment: Commitment) -> None:
    """CXP-06/GLO-03: with abonos it is canceled, never deleted (409)."""
    has_abonos = await session.scalar(
        select(Transaction.id).where(Transaction.commitment_id == commitment.id).limit(1)
    )
    if has_abonos is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El compromiso tiene abonos; cancélalo en lugar de eliminarlo",
        )
    await _cancel_reminders(session, [commitment.id], keep=set())
    await session.delete(commitment)
    await session.commit()


# --- Abonos (CXP-03) -------------------------------------------------------------------


async def validate_abono(
    session: AsyncSession,
    space_id: uuid.UUID,
    *,
    commitment_id: uuid.UUID | None,
    txn_type: TransactionType,
    currency: str,
    amount: Decimal,
    event_id: uuid.UUID | None,
    txn_id: uuid.UUID | None = None,
    current_commitment_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """CXP-03: an abono is an expense in the commitment's currency, inside its
    event, that never leaves the pending below zero. Returns the event the
    transaction must carry (inherited from the commitment)."""
    if commitment_id is None:
        return event_id
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None or commitment.space_id != space_id:
        raise _reject("El compromiso no existe")
    if txn_type != TransactionType.expense:
        raise _reject("Solo un gasto puede ser abono a un compromiso")
    if commitment.is_canceled and commitment_id != current_commitment_id:
        raise _reject(f"El compromiso {commitment.name} está cancelado")
    if currency != commitment.currency:
        raise _reject(
            f"El compromiso {commitment.name} se pactó en {commitment.currency}; "
            f"abona con una cuenta en {commitment.currency}"
        )
    if commitment.event_id is not None:
        if event_id is None:
            event_id = commitment.event_id
        elif event_id != commitment.event_id:
            raise _reject("Un abono pertenece al evento de su compromiso")
    excluded = (txn_id,) if txn_id is not None else ()
    tracked, _ = (await tracked_payments(session, [commitment.id], excluded)).get(
        commitment.id, (ZERO, 0)
    )
    pending = commitment.total_amount - commitment.paid_before_tracking - tracked
    if amount > pending:
        raise _reject(
            f"El abono excede lo pendiente de {commitment.name} ({pending}). "
            "Si el proveedor cobró extras, primero edita el total del compromiso."
        )
    return event_id


async def ensure_gifts_category(
    session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID
) -> Category:
    """CAT-02: 'Regalos recibidos' (income); recreated if the user removed it."""
    normalized = normalize_name(GIFTS_CATEGORY_NAME)
    category: Category | None = await session.scalar(
        select(Category).where(
            Category.space_id == space_id,
            Category.kind == CategoryKind.income,
            Category.name_normalized == normalized,
        )
    )
    if category is None:
        category = Category(
            space_id=space_id,
            name=GIFTS_CATEGORY_NAME,
            name_normalized=normalized,
            kind=CategoryKind.income,
            created_by=created_by,
        )
        session.add(category)
        await session.flush()
    elif not category.is_active:
        category.is_active = True  # CAT-04: reactivable; the gift needs it
    return category


async def pay_by_third_party(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    commitment: Commitment,
    *,
    amount: Decimal,
    date: dt.date,
    account_id: uuid.UUID,
    description: str,
    category_id: uuid.UUID | None,
) -> tuple[Transaction, Transaction]:
    """CXP-04: someone paid the vendor directly as a gift. Atomically creates
    the 'Regalos recibidos' income and the abono expense (same amount, date,
    account and event); the account's balance doesn't move."""
    from app.services.accounts import account_behavior
    from app.services.transactions import (
        TransactionInput,
        create_transaction,
        validate_account,
    )

    account = await validate_account(session, space.id, account_id)
    # A credit card would turn the gift into a statement refund (TDC-16).
    if await account_behavior(session, account) not in BALANCE_BEHAVIORS:
        raise _reject("Elige una cuenta con saldo (efectivo, débito…), no una tarjeta de crédito")
    expense_category = category_id or commitment.category_id
    if expense_category is None:
        raise _reject("Elige la categoría del gasto")
    gifts = await ensure_gifts_category(session, space.id, created_by)
    label = description.strip() or f"{commitment.name} (pagado por un tercero)"
    common: dict[str, Any] = {
        "date": date,
        "amount": amount,
        "currency": account.currency,
        "account_id": account.id,
        "event_id": commitment.event_id,
    }
    income = await create_transaction(
        session,
        space,
        created_by,
        TransactionInput(
            type=TransactionType.income,
            category_id=gifts.id,
            description=f"Regalo: {label}"[:200],
            **common,
        ),
        commit=False,
    )
    expense = await create_transaction(
        session,
        space,
        created_by,
        TransactionInput(
            type=TransactionType.expense,
            category_id=expense_category,
            description=label[:200],
            commitment_id=commitment.id,
            **common,
        ),
        commit=False,
    )
    await session.commit()
    await session.refresh(income)
    await session.refresh(expense)
    return income, expense


# --- What is still owed (CXP-07/08, DSH-05) ---------------------------------------------


@dataclass
class Obligation:
    commitment: Commitment
    ref_id: uuid.UUID  # schedule row, or the commitment for its unscheduled part
    due_date: dt.date | None  # None: pending without any date (CXP-07)
    amount: Decimal  # in the commitment's currency
    is_overdue: bool


async def pending_obligations(
    session: AsyncSession, space: Space, event_id: uuid.UUID | None = None
) -> list[Obligation]:
    """Uncovered schedule rows plus the unscheduled pending of every pending
    commitment (dated by `due_date`, or undated)."""
    today = today_in_tz(space.timezone)
    result: list[Obligation] = []
    for state in await list_commitments(session, space, event_id=event_id):
        for row in state.schedule:
            if not row.is_covered:
                result.append(
                    Obligation(
                        state.commitment, row.id, row.due_date, row.uncovered, row.is_overdue
                    )
                )
        if state.unscheduled_pending > ZERO:
            due = state.commitment.due_date
            result.append(
                Obligation(
                    state.commitment,
                    state.commitment.id,
                    due,
                    state.unscheduled_pending,
                    due is not None and due < today,
                )
            )
    return result


# --- Reminders (CXP-08) ----------------------------------------------------------------


def _due_items(state: CommitmentState) -> list[tuple[uuid.UUID, dt.date, Decimal]]:
    """(reminder ref, due date, amount) for what is still owed with a date."""
    items = [(r.id, r.due_date, r.uncovered) for r in state.schedule if not r.is_covered]
    if state.unscheduled_pending > ZERO and state.commitment.due_date is not None:
        items.append((state.commitment.id, state.commitment.due_date, state.unscheduled_pending))
    return items


async def _cancel_reminders(
    session: AsyncSession, commitment_ids: Collection[uuid.UUID], keep: set[uuid.UUID]
) -> None:
    """Cancel pending/sent reminders of these commitments whose ref is no
    longer owed (like REM-01b). Refs are schedule rows or the commitment."""
    if not commitment_ids:
        return
    row_ids = (
        (
            await session.execute(
                select(CommitmentPayment.id).where(
                    CommitmentPayment.commitment_id.in_(list(commitment_ids))
                )
            )
        )
        .scalars()
        .all()
    )
    refs = set(row_ids) | set(commitment_ids)
    reminders = (
        (
            await session.execute(
                select(Reminder).where(
                    Reminder.kind == ReminderKind.commitment_due,
                    Reminder.ref_id.in_(list(refs)),
                    Reminder.status.in_([ReminderStatus.pending, ReminderStatus.sent]),
                )
            )
        )
        .scalars()
        .all()
    )
    for reminder in reminders:
        if reminder.ref_id not in keep:
            reminder.status = ReminderStatus.canceled


async def sync_reminders(
    session: AsyncSession, space: Space, commitment_ids: Collection[uuid.UUID] | None = None
) -> None:
    """CXP-08: reminders at due − [3, 1] days for what is still owed (only
    fire_at ≥ today, like REM-01); canceled as soon as it gets covered."""
    stmt = (
        select(Commitment)
        .options(selectinload(Commitment.payments))
        .where(Commitment.space_id == space.id)
    )
    if commitment_ids is not None:
        stmt = stmt.where(Commitment.id.in_(list(commitment_ids)))
    commitments = (await session.execute(stmt)).scalars().all()
    states = await states_for(session, space, commitments)
    today = today_in_tz(space.timezone)
    keep: set[uuid.UUID] = set()
    for state in states:
        if state.status != "pending":
            continue
        name = " ".join(state.commitment.name.split())  # CWE-117, like REM-03
        for ref_id, due, amount in _due_items(state):
            keep.add(ref_id)
            message = (
                f"Pago a {name}: ${amount} {state.commitment.currency} antes del {due.isoformat()}"
            )
            for offset in REMINDER_OFFSETS:
                fire_at = due - dt.timedelta(days=offset)
                if fire_at < today:
                    continue
                for channel in REMINDER_CHANNELS:
                    existing: Reminder | None = await session.scalar(
                        select(Reminder).where(
                            Reminder.kind == ReminderKind.commitment_due,
                            Reminder.ref_id == ref_id,
                            Reminder.offset_days == offset,
                            Reminder.channel == channel,
                        )
                    )
                    if existing is None:
                        session.add(
                            Reminder(
                                space_id=space.id,
                                kind=ReminderKind.commitment_due,
                                ref_id=ref_id,
                                offset_days=offset,
                                fire_at=fire_at,
                                channel=channel,
                                message=message,
                            )
                        )
                    elif existing.status == ReminderStatus.pending:
                        existing.fire_at = fire_at  # the date or amount may have changed
                        existing.message = message
    await _cancel_reminders(session, [c.id for c in commitments], keep)
    await session.flush()
