"""Router: events. Implements EVT-01..EVT-03 and EVT-05 (filter lives in
/transactions)."""

import uuid

from fastapi import APIRouter, status

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.events import Event
from app.models.spaces import Space
from app.schemas.dashboard import CategoryBreakdownRow
from app.schemas.events import (
    EventCreate,
    EventLoanOut,
    EventOut,
    EventSummaryOut,
    EventUpdate,
)
from app.services import events as svc

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventSummaryOut])
async def list_events(
    db: DbSession, space_and_member: ActiveSpace, include_inactive: bool = False
) -> list[EventSummaryOut]:
    """EVT-01/03: events of the active space, each with its summary."""
    space, _ = space_and_member
    events = await svc.list_events(db, space.id, include_inactive)
    return [await _summary_out(db, space, event) for event in events]


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: EventCreate
) -> EventOut:
    space, _ = space_and_member
    event = await svc.create_event(db, space, user.id, payload.model_dump())
    return EventOut.model_validate(event)


@router.get("/{event_id}", response_model=EventSummaryOut)
async def get_event(
    db: DbSession, space_and_member: ActiveSpace, event_id: uuid.UUID
) -> EventSummaryOut:
    """EVT-03: spent, received, net, budget and linked loans."""
    space, _ = space_and_member
    return await _summary_out(db, space, await svc.get_event(db, space.id, event_id))


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    db: DbSession, space_and_member: EditorSpace, event_id: uuid.UUID, payload: EventUpdate
) -> EventOut:
    space, _ = space_and_member
    event = await svc.get_event(db, space.id, event_id)
    event = await svc.update_event(db, event, payload.model_dump(exclude_unset=True))
    return EventOut.model_validate(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(db: DbSession, space_and_member: EditorSpace, event_id: uuid.UUID) -> None:
    """GLO-03: 409 when it has linked movements (deactivate it instead)."""
    space, _ = space_and_member
    await svc.delete_event(db, await svc.get_event(db, space.id, event_id))


async def _summary_out(db: DbSession, space: Space, event: Event) -> EventSummaryOut:
    summary = await svc.event_summary(db, space, event)
    return EventSummaryOut(
        event=EventOut.model_validate(event),
        spent=summary["spent"],
        spent_before_tracking=summary["spent_before_tracking"],
        received=summary["received"],
        net=summary["net"],
        budget_remaining=summary["budget_remaining"],
        pending_commitments=summary["pending_commitments"],
        movements=summary["movements"],
        by_category=[CategoryBreakdownRow(**row) for row in summary["by_category"]],
        loans=[EventLoanOut.model_validate(loan) for loan in summary["loans"]],
    )
