"""Router: centro de notificaciones in-app. Implementa REM-04..REM-07."""

import uuid

from fastapi import APIRouter, status

from app.core.deps import ActiveSpace, DbSession
from app.models.reminders import Reminder
from app.schemas.notifications import MarkedReadOut, NotificationOut, UnreadCountOut
from app.services import reminders as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(db: DbSession, space_and_member: ActiveSpace) -> list[Reminder]:
    """REM-06: inbox del espacio activo — solo avisos ya disparados y no descartados."""
    space, _ = space_and_member
    return await svc.list_inbox(db, space)


@router.get("/unread-count", response_model=UnreadCountOut)
async def get_unread_count(db: DbSession, space_and_member: ActiveSpace) -> UnreadCountOut:
    """REM-07: badge de la campana."""
    space, _ = space_and_member
    return UnreadCountOut(unread=await svc.unread_count(db, space))


@router.get("/history", response_model=list[NotificationOut])
async def list_history(db: DbSession, space_and_member: ActiveSpace) -> list[Reminder]:
    """REM-06: auditoría — todos los estados y canales del espacio activo."""
    space, _ = space_and_member
    return await svc.list_history(db, space)


@router.post("/read-all", response_model=MarkedReadOut)
async def read_all(db: DbSession, space_and_member: ActiveSpace) -> MarkedReadOut:
    """REM-07: marca leído todo el inbox (idempotente); no altera `status`."""
    space, _ = space_and_member
    return MarkedReadOut(marked=await svc.mark_all_read(db, space))


@router.post("/{reminder_id}/read", response_model=NotificationOut)
async def read_one(
    db: DbSession, space_and_member: ActiveSpace, reminder_id: uuid.UUID
) -> Reminder:
    """REM-07: marca leído un aviso; sigue visible hasta descartarlo (REM-05)."""
    space, _ = space_and_member
    return await svc.mark_read(db, space, reminder_id)


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_notification(
    db: DbSession, space_and_member: ActiveSpace, reminder_id: uuid.UUID
) -> None:
    """REM-05: descartar (soft-delete). Solo del espacio activo (GLO-05)."""
    space, _ = space_and_member
    await svc.dismiss(db, space, reminder_id)
