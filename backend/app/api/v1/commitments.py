"""Router: vendor commitments. Implements CXP-01..CXP-06 (abonos are created
through /transactions with `commitment_id`, CXP-03)."""

import uuid

from fastapi import APIRouter, status

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.spaces import Space
from app.schemas.commitments import (
    CommitmentCreate,
    CommitmentOut,
    CommitmentUpdate,
    ScheduleRowOut,
    ThirdPartyOut,
    ThirdPartyPayment,
)
from app.schemas.transactions import TransactionOut
from app.services import commitments as svc
from app.services.commitments import CommitmentState

router = APIRouter(prefix="/commitments", tags=["commitments"])


def _out(state: CommitmentState) -> CommitmentOut:
    c = state.commitment
    return CommitmentOut(
        id=c.id,
        name=c.name,
        total_amount=c.total_amount,
        currency=c.currency,
        event_id=c.event_id,
        category_id=c.category_id,
        paid_before_tracking=c.paid_before_tracking,
        due_date=c.due_date,
        notes=c.notes,
        is_canceled=c.is_canceled,
        paid=state.paid,
        pending=state.pending,
        status=state.status,
        is_overdue=state.is_overdue,
        abonos=state.abonos,
        schedule=[ScheduleRowOut.model_validate(row) for row in state.schedule],
        unscheduled_pending=state.unscheduled_pending,
    )


async def _state_out(db: DbSession, space: Space, commitment_id: uuid.UUID) -> CommitmentOut:
    commitment = await svc.get_commitment(db, space.id, commitment_id)
    return _out(await svc.commitment_state(db, space, commitment))


@router.get("", response_model=list[CommitmentOut])
async def list_commitments(
    db: DbSession,
    space_and_member: ActiveSpace,
    include_closed: bool = False,
    event_id: uuid.UUID | None = None,
) -> list[CommitmentOut]:
    """CXP-05: paid/canceled hidden unless include_closed."""
    space, _ = space_and_member
    states = await svc.list_commitments(db, space, include_closed=include_closed, event_id=event_id)
    return [_out(state) for state in states]


@router.post("", response_model=CommitmentOut, status_code=status.HTTP_201_CREATED)
async def create_commitment(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: CommitmentCreate
) -> CommitmentOut:
    space, _ = space_and_member
    commitment = await svc.create_commitment(db, space, user.id, payload.model_dump())
    return _out(await svc.commitment_state(db, space, commitment))


@router.get("/{commitment_id}", response_model=CommitmentOut)
async def get_commitment(
    db: DbSession, space_and_member: ActiveSpace, commitment_id: uuid.UUID
) -> CommitmentOut:
    space, _ = space_and_member
    return await _state_out(db, space, commitment_id)


@router.patch("/{commitment_id}", response_model=CommitmentOut)
async def update_commitment(
    db: DbSession,
    space_and_member: EditorSpace,
    commitment_id: uuid.UUID,
    payload: CommitmentUpdate,
) -> CommitmentOut:
    space, _ = space_and_member
    commitment = await svc.get_commitment(db, space.id, commitment_id)
    commitment = await svc.update_commitment(
        db, space, commitment, payload.model_dump(exclude_unset=True)
    )
    return _out(await svc.commitment_state(db, space, commitment))


@router.delete("/{commitment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_commitment(
    db: DbSession, space_and_member: EditorSpace, commitment_id: uuid.UUID
) -> None:
    """CXP-06: 409 with abonos (cancel it instead)."""
    space, _ = space_and_member
    await svc.delete_commitment(db, space, await svc.get_commitment(db, space.id, commitment_id))


@router.post("/{commitment_id}/third-party", response_model=ThirdPartyOut)
async def pay_by_third_party(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    commitment_id: uuid.UUID,
    payload: ThirdPartyPayment,
) -> ThirdPartyOut:
    """CXP-04: gift income + abono expense, atomically."""
    space, _ = space_and_member
    commitment = await svc.get_commitment(db, space.id, commitment_id)
    income, expense = await svc.pay_by_third_party(
        db,
        space,
        user.id,
        commitment,
        amount=payload.amount,
        date=payload.date,
        account_id=payload.account_id,
        description=payload.description,
        category_id=payload.category_id,
    )
    return ThirdPartyOut(
        income=TransactionOut.model_validate(income),
        expense=TransactionOut.model_validate(expense),
        commitment=await _state_out(db, space, commitment_id),
    )
