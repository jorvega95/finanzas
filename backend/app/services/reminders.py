"""Recordatorios. Implementa REM-01..REM-04."""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cards import Card, CardStatement
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # REM-02


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
