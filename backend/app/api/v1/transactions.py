"""Router: transactions. Implements TXN-01..TXN-14, REC-03 (review tray)."""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query, status
from sqlalchemy import func, or_, select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.transactions import Transaction, TransactionType
from app.schemas.accounts import MoveCycle
from app.schemas.transactions import (
    TransactionConfirm,
    TransactionCreate,
    TransactionEventUpdate,
    TransactionListOut,
    TransactionOut,
    TransactionUpdate,
)
from app.services import transactions as svc
from app.services.transactions import TransactionInput

router = APIRouter(prefix="/transactions", tags=["transactions"])


async def transactions_out(db: DbSession, txns: Sequence[Transaction]) -> list[TransactionOut]:
    """TransactionOut with each transfer's fee (TXN-14), in one extra query."""
    fees = await svc.fee_amounts(db, txns)
    out = []
    for txn in txns:
        item = TransactionOut.model_validate(txn)
        item.fee_amount = fees.get(txn.id)
        out.append(item)
    return out


async def transaction_out(db: DbSession, txn: Transaction) -> TransactionOut:
    return (await transactions_out(db, [txn]))[0]


def _to_input(payload: TransactionCreate | TransactionUpdate) -> TransactionInput:
    return TransactionInput(
        type=payload.type,
        date=payload.date,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        notes=payload.notes,
        category_id=payload.category_id,
        account_id=payload.account_id,
        account_to_id=payload.account_to_id,
        amount_to=payload.amount_to,
        fee_amount=payload.fee_amount,
        expense_nature_override=payload.expense_nature_override,
        fx_rate_override=payload.fx_rate_override,
        cycle_hint=payload.cycle_hint,
        target_statement_id=payload.target_statement_id,  # TXN-09
        event_id=payload.event_id,  # EVT-02
    )


@router.get("", response_model=TransactionListOut)
async def list_transactions(
    db: DbSession,
    space_and_member: ActiveSpace,
    date_from: date | None = None,
    date_to: date | None = None,
    type: TransactionType | None = None,
    category_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    needs_review: bool | None = None,
    q: str | None = Query(None, max_length=200),
    limit: int = 50,
    offset: int = 0,
) -> TransactionListOut:
    space, _ = space_and_member
    filters = [Transaction.space_id == space.id]
    if date_from is not None:
        filters.append(Transaction.date >= date_from)
    if date_to is not None:
        filters.append(Transaction.date <= date_to)
    if type is not None:
        filters.append(Transaction.type == type)
    if category_id is not None:
        filters.append(Transaction.category_id == category_id)
    if account_id is not None:
        # TXN-10: the filter means "movements touching this account", so
        # transfers match on either leg (source or destination).
        filters.append(
            or_(Transaction.account_id == account_id, Transaction.account_to_id == account_id)
        )
    if event_id is not None:
        filters.append(Transaction.event_id == event_id)  # EVT-05
    if needs_review is not None:
        filters.append(Transaction.needs_review.is_(needs_review))
    if q is not None and q.strip():
        # TXN-12: case-insensitive substring over description; wildcards literal.
        filters.append(Transaction.description.ilike(svc.like_pattern(q), escape="\\"))

    total = await db.scalar(select(func.count()).select_from(Transaction).where(*filters))
    rows = await db.execute(
        select(Transaction)
        .where(*filters)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(min(limit, 500))
        .offset(offset)
    )
    items = await transactions_out(db, rows.scalars().all())
    return TransactionListOut(items=items, total=total or 0)


@router.get("/duplicates", response_model=list[TransactionOut])
async def list_possible_duplicates(
    db: DbSession,
    space_and_member: ActiveSpace,
    type: TransactionType,
    date: date,
    amount: Decimal,
    currency: str,
    description: str = "",
    category_id: uuid.UUID | None = None,
) -> list[TransactionOut]:
    """TXN-11: existing transactions that look like the one about to be created
    (account deliberately ignored). Advisory only; never blocks POST."""
    space, _ = space_and_member
    rows = await svc.find_possible_duplicates(
        db, space.id, type, date, amount, currency, description, category_id
    )
    return await transactions_out(db, rows)


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: TransactionCreate
) -> TransactionOut:
    space, _ = space_and_member
    txn = await svc.create_transaction(db, space, user.id, _to_input(payload))
    return await transaction_out(db, txn)


@router.get("/{txn_id}", response_model=TransactionOut)
async def get_transaction(
    db: DbSession, space_and_member: ActiveSpace, txn_id: uuid.UUID
) -> TransactionOut:
    space, _ = space_and_member
    return await transaction_out(db, await svc.get_transaction(db, space.id, txn_id))


@router.put("/{txn_id}", response_model=TransactionOut)
async def update_transaction(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    txn_id: uuid.UUID,
    payload: TransactionUpdate,
) -> TransactionOut:
    space, _ = space_and_member
    txn = await svc.update_transaction(db, space, user.id, txn_id, _to_input(payload))
    return await transaction_out(db, txn)


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    db: DbSession, space_and_member: EditorSpace, txn_id: uuid.UUID
) -> None:
    space, _ = space_and_member
    await svc.delete_transaction(db, space.id, txn_id)


@router.patch("/{txn_id}/event", response_model=TransactionOut)
async def set_event(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    txn_id: uuid.UUID,
    payload: TransactionEventUpdate,
) -> TransactionOut:
    """EVT-02: link/unlink one transaction to an event (MSI parents included)."""
    space, _ = space_and_member
    txn = await svc.set_transaction_event(db, space.id, user.id, txn_id, payload.event_id)
    return await transaction_out(db, txn)


@router.post("/{txn_id}/confirm", response_model=TransactionOut)
async def confirm_transaction(
    db: DbSession, space_and_member: EditorSpace, txn_id: uuid.UUID, payload: TransactionConfirm
) -> TransactionOut:
    """REC-03: confirm an instance from the review tray (optional new amount)."""
    space, _ = space_and_member
    txn = await svc.confirm_transaction(db, space.id, txn_id, payload.amount)
    return await transaction_out(db, txn)


@router.post("/{txn_id}/move-cycle", response_model=TransactionOut)
async def move_cycle(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    txn_id: uuid.UUID,
    payload: MoveCycle,
) -> TransactionOut:
    """TDC-06: move a card charge to the previous/next billing cycle."""
    from app.services.accounts import move_charge_cycle

    space, _ = space_and_member
    txn = await svc.get_transaction(db, space.id, txn_id)
    txn = await move_charge_cycle(db, space, user.id, txn, payload.direction)
    return await transaction_out(db, txn)
