"""Router: transactions. Implements TXN-01..TXN-06, REC-03 (review tray)."""

import uuid
from datetime import date

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.transactions import Transaction, TransactionType
from app.schemas.cards import MoveCycle
from app.schemas.transactions import (
    TransactionConfirm,
    TransactionCreate,
    TransactionListOut,
    TransactionOut,
    TransactionUpdate,
)
from app.services import transactions as svc
from app.services.transactions import TransactionInput

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _to_input(payload: TransactionCreate | TransactionUpdate) -> TransactionInput:
    return TransactionInput(
        type=payload.type,
        date=payload.date,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        notes=payload.notes,
        category_id=payload.category_id,
        payment_method_id=payload.payment_method_id,
        payment_method_to_id=payload.payment_method_to_id,
        expense_nature_override=payload.expense_nature_override,
        fx_rate_override=payload.fx_rate_override,
        cycle_hint=payload.cycle_hint,
        target_statement_id=payload.target_statement_id,  # TXN-09
    )


@router.get("", response_model=TransactionListOut)
async def list_transactions(
    db: DbSession,
    space_and_member: ActiveSpace,
    date_from: date | None = None,
    date_to: date | None = None,
    type: TransactionType | None = None,
    category_id: uuid.UUID | None = None,
    payment_method_id: uuid.UUID | None = None,
    needs_review: bool | None = None,
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
    if payment_method_id is not None:
        filters.append(Transaction.payment_method_id == payment_method_id)
    if needs_review is not None:
        filters.append(Transaction.needs_review.is_(needs_review))

    total = await db.scalar(select(func.count()).select_from(Transaction).where(*filters))
    rows = await db.execute(
        select(Transaction)
        .where(*filters)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(min(limit, 200))
        .offset(offset)
    )
    items = [TransactionOut.model_validate(t) for t in rows.scalars().all()]
    return TransactionListOut(items=items, total=total or 0)


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: TransactionCreate
) -> TransactionOut:
    space, _ = space_and_member
    txn = await svc.create_transaction(db, space, user.id, _to_input(payload))
    return TransactionOut.model_validate(txn)


@router.get("/{txn_id}", response_model=TransactionOut)
async def get_transaction(
    db: DbSession, space_and_member: ActiveSpace, txn_id: uuid.UUID
) -> TransactionOut:
    space, _ = space_and_member
    return TransactionOut.model_validate(await svc.get_transaction(db, space.id, txn_id))


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
    return TransactionOut.model_validate(txn)


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    db: DbSession, space_and_member: EditorSpace, txn_id: uuid.UUID
) -> None:
    space, _ = space_and_member
    await svc.delete_transaction(db, space.id, txn_id)


@router.post("/{txn_id}/confirm", response_model=TransactionOut)
async def confirm_transaction(
    db: DbSession, space_and_member: EditorSpace, txn_id: uuid.UUID, payload: TransactionConfirm
) -> TransactionOut:
    """REC-03: confirm an instance from the review tray (optional new amount)."""
    space, _ = space_and_member
    txn = await svc.confirm_transaction(db, space.id, txn_id, payload.amount)
    return TransactionOut.model_validate(txn)


@router.post("/{txn_id}/move-cycle", response_model=TransactionOut)
async def move_cycle(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    txn_id: uuid.UUID,
    payload: MoveCycle,
) -> TransactionOut:
    """TDC-06: move a card charge to the previous/next billing cycle."""
    from app.services.cards import move_charge_cycle

    space, _ = space_and_member
    txn = await svc.get_transaction(db, space.id, txn_id)
    txn = await move_charge_cycle(db, space, user.id, txn, payload.direction)
    return TransactionOut.model_validate(txn)
