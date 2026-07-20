"""Recordatorios. Implementa REM-01..REM-07."""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cards import Card, CardStatement
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Space

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # REM-02
INBOX_LIMIT = 50
HISTORY_LIMIT = 100


async def schedule_card_reminders(
    session: AsyncSession,
    card: Card,
    statement: CardStatement,
    today: date | None = None,
) -> None:
    """REM-01: al cerrar un statement se programan recordatorios a
    due_date − N para cada N de card.reminder_days, por canal (REM-04).
    Único por (statement, offset, canal) — REM-02.

    REM-01: solo se crean recordatorios con fire_at >= today. Si today es None
    no se filtra (compatibilidad con llamadas sin contexto de fecha)."""
    amount_due = statement.computed_total - statement.paid_amount
    if amount_due <= 0:
        return
    # REM-03: alias + monto + fecha límite; nunca last4.
    message = f"Pago de {card.alias}: ${amount_due} antes del {statement.due_date.isoformat()}"
    for offset in card.reminder_days:
        fire_at = statement.due_date - timedelta(days=int(offset))
        # REM-01: skip past fire dates to avoid immediate spurious notifications
        # when closing historical statements (backfill, opening balance, etc.).
        if today is not None and fire_at < today:
            continue
        for channel in (ReminderChannel.in_app, ReminderChannel.email):
            exists_already = await session.scalar(
                select(Reminder.id).where(
                    Reminder.kind == ReminderKind.card_due,
                    Reminder.ref_id == statement.id,
                    Reminder.offset_days == int(offset),
                    Reminder.channel == channel,
                )
            )
            if exists_already is None:
                session.add(
                    Reminder(
                        space_id=statement.space_id,
                        kind=ReminderKind.card_due,
                        ref_id=statement.id,
                        offset_days=int(offset),
                        fire_at=fire_at,
                        channel=channel,
                        message=message,
                    )
                )
    await session.flush()


async def cancel_card_reminders(session: AsyncSession, statement: CardStatement) -> None:
    """REM-01b: al pagar un statement se cancelan sus recordatorios pending Y sent,
    para que desaparezcan del inbox en cuanto se registra el pago."""
    reminders = (
        (
            await session.execute(
                select(Reminder).where(
                    Reminder.kind == ReminderKind.card_due,
                    Reminder.ref_id == statement.id,
                    Reminder.status.in_([ReminderStatus.pending, ReminderStatus.sent]),
                )
            )
        )
        .scalars()
        .all()
    )
    for reminder in reminders:
        reminder.status = ReminderStatus.canceled
    await session.flush()


def _inbox_filter(space: Space) -> Select[tuple[Reminder]]:
    """REM-06: canal in_app del espacio activo (GLO-05), ya disparados y no
    descartados. Excluye pending (futuros), canceled (REM-01b) y dismissed."""
    return select(Reminder).where(
        Reminder.space_id == space.id,
        Reminder.channel == ReminderChannel.in_app,
        Reminder.status == ReminderStatus.sent,
    )


async def list_inbox(session: AsyncSession, space: Space) -> list[Reminder]:
    """REM-06: centro de notificaciones in-app del espacio activo."""
    rows = await session.execute(
        _inbox_filter(space)
        .order_by(Reminder.fire_at.desc(), Reminder.created_at.desc())
        .limit(INBOX_LIMIT)
    )
    return list(rows.scalars().all())


async def list_history(session: AsyncSession, space: Space) -> list[Reminder]:
    """REM-06: auditoría — todos los estados y canales del espacio activo."""
    rows = await session.execute(
        select(Reminder)
        .where(Reminder.space_id == space.id)
        .order_by(Reminder.fire_at.desc(), Reminder.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    return list(rows.scalars().all())


async def unread_count(session: AsyncSession, space: Space) -> int:
    """REM-07: badge de la campana = avisos del inbox sin leer."""
    total: int | None = await session.scalar(
        select(func.count()).select_from(
            _inbox_filter(space).where(Reminder.read_at.is_(None)).subquery()
        )
    )
    return total or 0


async def get_reminder(session: AsyncSession, space: Space, reminder_id: uuid.UUID) -> Reminder:
    """GLO-05: un recordatorio de otro espacio no existe para este usuario (404)."""
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None or reminder.space_id != space.id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Recordatorio no encontrado")
    return reminder


async def mark_read(session: AsyncSession, space: Space, reminder_id: uuid.UUID) -> Reminder:
    """REM-07: marcar leído es idempotente y no altera `status`."""
    reminder = await get_reminder(session, space, reminder_id)
    if reminder.read_at is None:
        reminder.read_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(reminder)
    return reminder


async def mark_all_read(session: AsyncSession, space: Space) -> int:
    """REM-07: marca leído todo el inbox. Devuelve cuántos cambiaron."""
    unread_ids = (
        (await session.execute(_inbox_filter(space).where(Reminder.read_at.is_(None))))
        .scalars()
        .all()
    )
    if not unread_ids:
        return 0
    now = datetime.now(UTC)
    await session.execute(
        update(Reminder).where(Reminder.id.in_([r.id for r in unread_ids])).values(read_at=now)
    )
    await session.commit()
    return len(unread_ids)


async def dismiss(session: AsyncSession, space: Space, reminder_id: uuid.UUID) -> None:
    """REM-05: soft-delete — pasa a `dismissed`, se conserva para auditoría.
    No afecta el statement ni otros canales."""
    reminder = await get_reminder(session, space, reminder_id)
    reminder.status = ReminderStatus.dismissed
    await session.commit()


async def fire_due_reminders(session: AsyncSession, today: date) -> int:
    """Job: envía pendientes con fire_at <= hoy. In-app = marcar enviado;
    email vía Resend cuando haya API key (v1: log). Reintentos REM-02."""
    due = (
        (
            await session.execute(
                select(Reminder).where(
                    Reminder.status == ReminderStatus.pending,
                    Reminder.fire_at <= today,
                )
            )
        )
        .scalars()
        .all()
    )
    sent = 0
    for reminder in due:
        try:
            if reminder.channel == ReminderChannel.email:
                # v1: sin proveedor configurado se registra en log (REM-04).
                logger.info("email reminder: %s", reminder.message)
            reminder.status = ReminderStatus.sent
            reminder.sent_at = datetime.now(UTC)
            sent += 1
        except Exception:
            reminder.attempts += 1
            if reminder.attempts >= MAX_ATTEMPTS:
                reminder.status = ReminderStatus.failed
            logger.exception("reminder %s failed", reminder.id)
    await session.commit()
    return sent
