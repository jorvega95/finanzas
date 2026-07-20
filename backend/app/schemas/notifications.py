"""Schemas del centro de notificaciones in-app (REM-04..REM-07)."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict

from app.models.reminders import ReminderChannel, ReminderKind, ReminderStatus


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ReminderKind
    ref_id: uuid.UUID
    fire_at: dt.date
    channel: ReminderChannel
    # REM-03: alias + monto + fecha límite; nunca last4.
    message: str
    status: ReminderStatus
    sent_at: dt.datetime | None = None
    # REM-07: nulo = no leído (alimenta el badge de la campana).
    read_at: dt.datetime | None = None
    created_at: dt.datetime


class UnreadCountOut(BaseModel):
    unread: int


class MarkedReadOut(BaseModel):
    marked: int
