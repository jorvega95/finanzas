"""Invoicing and declaration reminders. Implements FAC-09.

- `invoice_pending` (ref = payment): on the payment day (offset 0) and three
  days before the month ends (offset 3), while it has no invoice.
- `tax_filing_due` (ref = deterministic id of space + period): on day 1 of
  the next month (offset 0) and three days before the deadline (offset 3),
  while the period is not settled. A new deadline (RFC digit, "vigente
  hasta") moves the pending ones; the key stays the same.

Channels in_app + desktop (REM-08). Only fire_at >= today is created (like
REM-01); idempotent by (kind, ref, offset, channel) (REM-02); whatever no
longer applies is canceled, sent ones included (like REM-01b).
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Space
from app.services import billing, tax_filings
from app.services.billing import STATUS_PENDING

CHANNELS = (ReminderChannel.in_app, ReminderChannel.desktop)
KINDS = (ReminderKind.invoice_pending, ReminderKind.tax_filing_due)
MONTH_END_OFFSET = 3
DEADLINE_OFFSET = 3
_PERIOD_NAMESPACE = uuid.UUID("5b0f8a3e-6c1d-4f6e-9a57-2f3c1b7d9e10")


def period_ref(space_id: uuid.UUID, period: dt.date) -> uuid.UUID:
    """Deterministic reminder ref of a fiscal period (it has no row)."""
    return uuid.uuid5(_PERIOD_NAMESPACE, f"{space_id}:{period.isoformat()}")


@dataclass(frozen=True)
class Wanted:
    kind: ReminderKind
    ref_id: uuid.UUID
    offset: int
    fire_at: dt.date
    message: str


def _money(value: object) -> str:
    return f"${value:,}"


async def _wanted(session: AsyncSession, space: Space) -> list[Wanted]:
    """Every reminder that still applies, past ones included: a past one is
    never created, but an already sent one must not be canceled for it."""
    wanted: list[Wanted] = []
    clients = {c.id: c.name for c in await billing.list_clients(session, space.id, True)}
    for state in await billing.list_payments(session, space.id, status_filter=STATUS_PENDING):
        p = state.payment
        client = " ".join(clients.get(p.client_id, "").split())  # CWE-117, like REM-03
        message = (
            f"Factura el cobro de {p.currency} {p.amount} del {p.payment_date.isoformat()}"
            f"{f' ({client})' if client else ''}"
        )
        month_end = p.payment_date + relativedelta(day=31)
        for offset, fire_at in (
            (0, p.payment_date),
            (MONTH_END_OFFSET, month_end - dt.timedelta(days=MONTH_END_OFFSET - 1)),
        ):
            wanted.append(Wanted(ReminderKind.invoice_pending, p.id, offset, fire_at, message))

    for period in await tax_filings.list_periods(session, space):
        if period.status == tax_filings.PERIOD_PAID:
            continue
        month = tax_filings.month_es(period.period)
        if period.status == tax_filings.PERIOD_TO_PAY:
            deadline = period.payment_deadline or period.deadline
            due = sum((f.amount_due for f in period.unpaid), tax_filings.ZERO)
            message = (
                f"Paga la declaración de {month}: {_money(due)} antes del {deadline.isoformat()}"
            )
        else:
            deadline = period.deadline
            amounts = (
                f": ingresos {_money(period.to_declare)}, ISR estimado "
                f"{_money(period.isr_estimate)}"
                if period.missing_rates == 0
                else ""  # a total without every rate would mislead
            )
            message = f"Declara {month} (RESICO){amounts}. Fecha límite {deadline.isoformat()}"
        ref = period_ref(space.id, period.period)
        opening = period.period + relativedelta(months=1)
        for offset, fire_at in (
            (0, opening),
            (DEADLINE_OFFSET, deadline - dt.timedelta(days=DEADLINE_OFFSET)),
        ):
            wanted.append(Wanted(ReminderKind.tax_filing_due, ref, offset, fire_at, message))
    return wanted


async def sync_reminders(session: AsyncSession, space: Space) -> None:
    """FAC-09: idempotent; flushes, the caller commits."""
    today = today_in_tz(space.timezone)
    wanted = await _wanted(session, space)
    existing = {
        (r.kind, r.ref_id, r.offset_days, r.channel): r
        for r in (
            await session.scalars(
                select(Reminder).where(Reminder.space_id == space.id, Reminder.kind.in_(KINDS))
            )
        ).all()
    }
    keep: set[tuple[ReminderKind, uuid.UUID, int, ReminderChannel]] = set()
    for w in wanted:
        for channel in CHANNELS:
            key = (w.kind, w.ref_id, w.offset, channel)
            keep.add(key)
            row = existing.get(key)
            if w.fire_at < today:
                continue  # like REM-01: nothing new in the past
            if row is None:
                session.add(
                    Reminder(
                        space_id=space.id,
                        kind=w.kind,
                        ref_id=w.ref_id,
                        offset_days=w.offset,
                        fire_at=w.fire_at,
                        channel=channel,
                        message=w.message,
                    )
                )
            elif row.status == ReminderStatus.pending:
                row.fire_at = w.fire_at
                row.message = w.message
            elif row.status == ReminderStatus.canceled:
                # It applies again (e.g. the invoice was removed): reschedule.
                row.status = ReminderStatus.pending
                row.fire_at = w.fire_at
                row.message = w.message
                row.sent_at = None
    for key, row in existing.items():
        if key not in keep and row.status in (ReminderStatus.pending, ReminderStatus.sent):
            row.status = ReminderStatus.canceled
    await session.flush()


async def sync_and_commit(session: AsyncSession, space: Space) -> None:
    await sync_reminders(session, space)
    await session.commit()
