"""Transacciones recurrentes y suscripciones. Implementa REC-01..REC-13.

Idempotencia por (recurring_rule_id, scheduled_date) — constraint único.
"""

import calendar
import uuid
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.accounts import Account
from app.models.catalogs import Category
from app.models.recurring import (
    RecurringFrequency,
    RecurringKind,
    RecurringRule,
    RecurringTombstone,
)
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import fx
from app.services.transactions import TransactionInput, create_transaction

# REC-12: default notice per kind (days before the charge).
DEFAULT_REMINDER_DAYS: dict[RecurringKind, list[int]] = {
    RecurringKind.generic: [],
    RecurringKind.subscription: [3],
    RecurringKind.bill: [0],
}
TRIAL_REMINDER_DAYS = 1  # REC-10
REMINDER_HORIZON_DAYS = 31  # REC-12: reminder_days ≤ 30
REMINDER_CHANNELS = (ReminderChannel.in_app, ReminderChannel.desktop)  # REM-08

# REC-13: monthly-equivalent factor per frequency.
MONTHLY_FACTOR: dict[RecurringFrequency, Decimal] = {
    RecurringFrequency.weekly: Decimal(52) / Decimal(12),
    RecurringFrequency.biweekly: Decimal(26) / Decimal(12),
    RecurringFrequency.semimonthly: Decimal(2),
    RecurringFrequency.monthly: Decimal(1),
    RecurringFrequency.bimonthly: Decimal(1) / Decimal(2),
    RecurringFrequency.yearly: Decimal(1) / Decimal(12),
}

CENTS = Decimal("0.01")
MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _monthly_day(year: int, month: int, rule: RecurringRule) -> int:
    """REC-01 day_rule: day N clamped to the month's last day, or last day."""
    last = calendar.monthrange(year, month)[1]
    if rule.use_last_day:
        return last
    return min(rule.month_day or 1, last)


def occurrences(rule: RecurringRule, until: date) -> Iterator[date]:
    """All scheduled dates of `rule` with scheduled_date <= until (REC-02/05).

    Pure date logic (GLO-02), independent of what was already generated —
    idempotency comes from the unique constraint + tombstones.
    """
    count = 0

    def _capped(d: date) -> bool:
        nonlocal count
        if rule.end_date is not None and d > rule.end_date:
            return False
        if rule.max_occurrences is not None and count >= rule.max_occurrences:
            return False
        count += 1
        return True

    if rule.frequency in (RecurringFrequency.weekly, RecurringFrequency.biweekly):
        step = timedelta(days=7 if rule.frequency == RecurringFrequency.weekly else 14)
        current = rule.start_date
        while current <= until:
            if not _capped(current):
                return
            yield current
            current += step
    elif rule.frequency == RecurringFrequency.semimonthly:
        # REC-06: fechas fijas por calendario (día 15 y último día del mes),
        # nunca "start_date + 14 días" — evita el desfase de `biweekly`.
        year, month = rule.start_date.year, rule.start_date.month
        while True:
            last = calendar.monthrange(year, month)[1]
            for day in sorted({15, last}):
                occurrence = date(year, month, day)
                if occurrence < rule.start_date:
                    continue
                if occurrence > until:
                    return
                if not _capped(occurrence):
                    return
                yield occurrence
            month += 1
            if month == 13:
                month, year = 1, year + 1
    elif rule.frequency in (RecurringFrequency.monthly, RecurringFrequency.bimonthly):
        # REC-06b: bimonthly = monthly day rule every 2 months from start_date.
        month_step = 2 if rule.frequency == RecurringFrequency.bimonthly else 1
        year, month = rule.start_date.year, rule.start_date.month
        while True:
            day = _monthly_day(year, month, rule)
            occurrence = date(year, month, day)
            if occurrence >= rule.start_date:
                if occurrence > until:
                    return
                if not _capped(occurrence):
                    return
                yield occurrence
            if occurrence > until:
                return
            month += month_step
            if month > 12:
                month, year = month - 12, year + 1
    else:  # yearly
        year = rule.start_date.year
        while True:
            last = calendar.monthrange(year, rule.start_date.month)[1]
            occurrence = date(year, rule.start_date.month, min(rule.start_date.day, last))
            if occurrence >= rule.start_date:
                if occurrence > until:
                    return
                if not _capped(occurrence):
                    return
                yield occurrence
            year += 1


def is_occurrence(rule: RecurringRule, day: date) -> bool:
    """Stops at `day` (the generator never runs past it)."""
    return any(occ == day for occ in occurrences(rule, day))


def rule_status(rule: RecurringRule, today: date) -> str:
    """REC-09/REC-10: derived state."""
    if rule.canceled_at is not None:
        return "canceled"
    if not rule.is_active:
        return "paused"
    if rule.is_trial and today < rule.start_date:
        return "trial"
    return "active"


def next_occurrence(rule: RecurringRule, today: date) -> date | None:
    """First scheduled date >= today (within a year and a bit)."""
    for occ in occurrences(rule, today + timedelta(days=400)):
        if occ >= today:
            return occ
    return None


async def _scheduled_dates(session: AsyncSession, rule_id: uuid.UUID) -> set[date]:
    """Occurrences already materialized (transaction) or discarded (tombstone)."""
    generated = (
        await session.execute(
            select(Transaction.scheduled_date).where(Transaction.recurring_rule_id == rule_id)
        )
    ).scalars()
    tombstones = (
        await session.execute(
            select(RecurringTombstone.scheduled_date).where(RecurringTombstone.rule_id == rule_id)
        )
    ).scalars()
    return {d for d in generated if d is not None} | set(tombstones)


async def generate_due_instances(session: AsyncSession, space: Space) -> int:
    """REC-02: daily job body for one space; generates every instance with
    scheduled_date <= today (REC-05 catch-up included). Idempotent: existing
    instances and tombstones are skipped. Returns the number created."""
    today = today_in_tz(space.timezone)
    created = 0

    rules = (
        (
            await session.execute(
                select(RecurringRule).where(
                    RecurringRule.space_id == space.id,
                    RecurringRule.is_active.is_(True),
                    # REC-11: bills are captured by the user, never generated.
                    RecurringRule.kind != RecurringKind.bill,
                )
            )
        )
        .scalars()
        .all()
    )
    for rule in rules:
        # REC-04: rules pointing at deactivated catalog entries auto-pause.
        category = await session.get(Category, rule.category_id) if rule.category_id else None
        account = await session.get(Account, rule.account_id)
        if (category is not None and not category.is_active) or (
            account is not None and not account.is_active
        ):
            rule.is_active = False
            await session.commit()
            continue
        if account is None or rule.amount is None:
            continue

        done = await _scheduled_dates(session, rule.id)
        for scheduled in occurrences(rule, today):
            if scheduled in done:
                continue
            amount = rule.amount
            original_amount: Decimal | None = None
            original_currency: str | None = None
            if rule.currency != account.currency:
                # REC-08: today's charge waits for today's FIX (FX-02); past
                # ones use the rate of their date or the closest previous.
                if scheduled == today and not await fx.has_rate_on(
                    session, rule.currency, account.currency, today
                ):
                    continue
                converted = await fx.convert(
                    session, rule.amount, rule.currency, account.currency, scheduled
                )
                if converted is None:
                    continue  # no known rate: retried on the next run
                amount = converted
                original_amount, original_currency = rule.amount, rule.currency
            await create_transaction(
                session,
                space,
                rule.created_by,
                TransactionInput(
                    type=rule.type,
                    date=scheduled,
                    amount=amount,
                    currency=account.currency,  # TAR-10
                    description=rule.description,
                    category_id=rule.category_id,
                    account_id=rule.account_id,
                ),
                recurring_rule_id=rule.id,
                scheduled_date=scheduled,
                needs_review=True,  # REC-03: born pending review.
                original_amount=original_amount,
                original_currency=original_currency,
            )
            created += 1
    return created


async def get_rule(session: AsyncSession, space_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringRule:
    rule = await session.get(RecurringRule, rule_id)
    if rule is None or rule.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regla no encontrada")
    return rule


def validate_rule_schedule(
    frequency: RecurringFrequency,
    start_date: date,
    month_day: int | None,
    use_last_day: bool,
    type: TransactionType,
) -> int | None:
    """REC-01 invariants; returns the effective month_day for monthly rules."""
    if type == TransactionType.transfer:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Las reglas recurrentes aplican a gastos e ingresos",
        )
    by_month = frequency in (RecurringFrequency.monthly, RecurringFrequency.bimonthly)
    if by_month and not use_last_day:
        return month_day or start_date.day
    return None if use_last_day or not by_month else month_day


def _reject(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def validate_rule_shape(
    *,
    kind: RecurringKind,
    type: TransactionType,
    amount: Decimal | None,
    currency: str,
    account: Account,
    is_trial: bool,
) -> None:
    """REC-07/08/10/11 invariants shared by create and update."""
    if kind != RecurringKind.generic and type != TransactionType.expense:
        raise _reject("Las suscripciones y los servicios solo pueden ser gastos")
    if amount is None and kind != RecurringKind.bill:
        raise _reject("El monto es obligatorio")
    if currency != account.currency and (
        type != TransactionType.expense or kind == RecurringKind.bill
    ):
        # TAR-10: only expense prices may be in another currency (REC-08).
        raise _reject(f"La cuenta {account.name} maneja {account.currency}")
    if is_trial and kind != RecurringKind.subscription:
        raise _reject("Solo las suscripciones pueden tener periodo de prueba")


# --- REC-11: variable bills ------------------------------------------------


@dataclass
class PendingBill:
    rule: RecurringRule
    scheduled_date: date


async def pending_bills(session: AsyncSession, space: Space) -> list[PendingBill]:
    """REC-11: occurrences <= today of active bills without a transaction or
    tombstone ("Por capturar"), oldest first."""
    today = today_in_tz(space.timezone)
    rules = (
        (
            await session.execute(
                select(RecurringRule).where(
                    RecurringRule.space_id == space.id,
                    RecurringRule.is_active.is_(True),
                    RecurringRule.kind == RecurringKind.bill,
                )
            )
        )
        .scalars()
        .all()
    )
    items: list[PendingBill] = []
    for rule in rules:
        done = await _scheduled_dates(session, rule.id)
        items.extend(PendingBill(rule, occ) for occ in occurrences(rule, today) if occ not in done)
    items.sort(key=lambda item: (item.scheduled_date, item.rule.description))
    return items


async def _bill_occurrence(
    session: AsyncSession, space: Space, rule_id: uuid.UUID, scheduled: date
) -> RecurringRule:
    rule = await get_rule(session, space.id, rule_id)
    if rule.kind != RecurringKind.bill:
        raise _reject("Solo los servicios variables se capturan")
    # Bounded work: a bill is captured around its date, never years ahead.
    if scheduled > today_in_tz(space.timezone) + timedelta(days=REMINDER_HORIZON_DAYS):
        raise _reject("Ese recibo aún no llega")
    if not is_occurrence(rule, scheduled):
        raise _reject("La fecha no corresponde a un recibo de este servicio")
    existing = await session.scalar(
        select(Transaction.id).where(
            Transaction.recurring_rule_id == rule.id, Transaction.scheduled_date == scheduled
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese recibo ya fue capturado")
    return rule


async def capture_bill(
    session: AsyncSession,
    space: Space,
    user_id: uuid.UUID,
    rule_id: uuid.UUID,
    scheduled: date,
    amount: Decimal,
    txn_date: date | None,
) -> Transaction:
    """REC-11: the user captures the real amount of a bill occurrence."""
    rule = await _bill_occurrence(session, space, rule_id, scheduled)
    account = await session.get(Account, rule.account_id)
    if account is None:
        raise _reject("La cuenta del servicio ya no existe")
    tombstone = await session.scalar(
        select(RecurringTombstone).where(
            RecurringTombstone.rule_id == rule.id, RecurringTombstone.scheduled_date == scheduled
        )
    )
    if tombstone is not None:
        await session.delete(tombstone)  # captured after all
    txn = await create_transaction(
        session,
        space,
        user_id,
        TransactionInput(
            type=TransactionType.expense,
            date=txn_date or scheduled,
            amount=amount,
            currency=account.currency,
            description=rule.description,
            category_id=rule.category_id,
            account_id=rule.account_id,
        ),
        recurring_rule_id=rule.id,
        scheduled_date=scheduled,
        commit=False,
    )
    await sync_reminders(session, space, [rule.id])
    await session.commit()
    await session.refresh(txn)
    return txn


async def skip_bill(
    session: AsyncSession, space: Space, rule_id: uuid.UUID, scheduled: date
) -> None:
    """REC-11: discard a bill occurrence (tombstone)."""
    rule = await _bill_occurrence(session, space, rule_id, scheduled)
    existing = await session.scalar(
        select(RecurringTombstone.id).where(
            RecurringTombstone.rule_id == rule.id, RecurringTombstone.scheduled_date == scheduled
        )
    )
    if existing is None:
        session.add(RecurringTombstone(rule_id=rule.id, scheduled_date=scheduled))
        await session.flush()
    await sync_reminders(session, space, [rule.id])
    await session.commit()


# --- REC-09: cancel / reactivate -------------------------------------------


async def cancel_rule(session: AsyncSession, space: Space, rule: RecurringRule) -> None:
    rule.is_active = False
    rule.canceled_at = today_in_tz(space.timezone)
    await session.flush()
    await sync_reminders(session, space, [rule.id])
    await session.commit()


async def reactivate_rule(session: AsyncSession, space: Space, rule: RecurringRule) -> None:
    rule.is_active = True
    rule.canceled_at = None
    await session.flush()
    await sync_reminders(session, space, [rule.id])
    await session.commit()


# --- REC-12: reminders -----------------------------------------------------


def _fmt_date(d: date) -> str:
    return f"{d.day} {MONTHS_ES[d.month - 1]}"


def _fmt_money(amount: Decimal, currency: str) -> str:
    return f"${amount:,.2f} {currency}"


def _reminder_ref(rule_id: uuid.UUID, scheduled: date) -> uuid.UUID:
    """REM-02: deterministic id per occurrence keeps the unique constraint."""
    return uuid.uuid5(rule_id, scheduled.isoformat())


def _message(rule: RecurringRule, account: Account | None, kind: ReminderKind, occ: date) -> str:
    # CWE-117 (como REM-03): texto libre sin saltos de línea.
    name = " ".join(rule.description.split())
    where = f" en {' '.join(account.name.split())}" if account is not None else ""
    if kind == ReminderKind.trial_ending:
        price = _fmt_money(rule.amount, rule.currency) if rule.amount is not None else ""
        text = (
            f"Tu prueba de {name} termina el {_fmt_date(occ)}: desde ese día se cobrará "
            f"{price}{where}. Cancélala antes si no la quieres."
        )
    elif kind == ReminderKind.bill_due:
        estimate = (
            f" (aprox. {_fmt_money(rule.amount, rule.currency)})" if rule.amount is not None else ""
        )
        text = f"Recibo de {name} del {_fmt_date(occ)}{estimate}: captura el monto."
    else:
        price = _fmt_money(rule.amount, rule.currency) if rule.amount is not None else ""
        text = f"{name} se cobra el {_fmt_date(occ)}: {price}{where}."
    return text[:300]


async def sync_reminders(
    session: AsyncSession, space: Space, rule_ids: Collection[uuid.UUID] | None = None
) -> None:
    """REC-12: keep the reminders of subscriptions, trials and bills in sync
    with their schedule. Idempotent (job hourly + after every change)."""
    today = today_in_tz(space.timezone)
    stmt = select(RecurringRule).where(
        RecurringRule.space_id == space.id, RecurringRule.kind != RecurringKind.generic
    )
    if rule_ids is not None:
        stmt = stmt.where(RecurringRule.id.in_(list(rule_ids)))
    rules = (await session.execute(stmt)).scalars().all()

    for rule in rules:
        active = rule.is_active and rule.canceled_at is None
        horizon = today + timedelta(days=REMINDER_HORIZON_DAYS)
        all_dates = set(occurrences(rule, horizon))
        is_bill = rule.kind == RecurringKind.bill
        handled = await _scheduled_dates(session, rule.id) if is_bill else set()
        account = await session.get(Account, rule.account_id)
        first = min(all_dates) if all_dates else None

        desired: dict[tuple[ReminderKind, uuid.UUID, int, ReminderChannel], tuple[date, str, date]]
        desired = {}
        if active:
            for occ in sorted(d for d in all_dates if d >= today and d not in handled):
                if rule.is_trial and occ == first:  # REC-10: the trial's end
                    kind, offsets = ReminderKind.trial_ending, [TRIAL_REMINDER_DAYS]
                elif is_bill:
                    kind, offsets = ReminderKind.bill_due, list(rule.reminder_days)
                else:
                    kind, offsets = ReminderKind.subscription_charge, list(rule.reminder_days)
                message = _message(rule, account, kind, occ)
                ref = _reminder_ref(rule.id, occ)
                for offset in offsets:
                    fire_at = occ - timedelta(days=int(offset))
                    if fire_at < today:  # like REM-01
                        continue
                    for channel in REMINDER_CHANNELS:
                        desired[(kind, ref, int(offset), channel)] = (fire_at, message, occ)

        existing = (
            (await session.execute(select(Reminder).where(Reminder.recurring_rule_id == rule.id)))
            .scalars()
            .all()
        )
        for reminder in existing:
            key = (reminder.kind, reminder.ref_id, reminder.offset_days, reminder.channel)
            wanted = desired.pop(key, None)
            if wanted is not None:
                fire_at, message, _ = wanted
                if reminder.status == ReminderStatus.canceled:
                    reminder.status = ReminderStatus.pending  # reactivated
                if reminder.status == ReminderStatus.pending:
                    reminder.fire_at, reminder.message = fire_at, message
                continue
            if reminder.status not in (ReminderStatus.pending, ReminderStatus.sent):
                continue
            ref_date = reminder.ref_date
            # Paused/canceled rule or bill already captured/skipped: like REM-01b.
            stale = not active or (ref_date is not None and ref_date in handled)
            if reminder.status == ReminderStatus.pending and not stale:
                # Not wanted anymore: the schedule changed, or the charge passed
                # before it could fire (a pending bill still deserves its notice).
                stale = (
                    reminder.fire_at >= today
                    or ref_date not in all_dates
                    or (not is_bill and ref_date is not None and ref_date < today)
                )
            if stale:
                reminder.status = ReminderStatus.canceled

        for (kind, ref, offset, channel), (fire_at, message, occ) in desired.items():
            session.add(
                Reminder(
                    space_id=space.id,
                    kind=kind,
                    ref_id=ref,
                    offset_days=offset,
                    fire_at=fire_at,
                    channel=channel,
                    message=message,
                    recurring_rule_id=rule.id,
                    ref_date=occ,
                )
            )
    await session.flush()


# --- REC-13: monthly cost ---------------------------------------------------


@dataclass
class SubscriptionSummary:
    monthly_total: Decimal
    yearly_total: Decimal
    currency: str
    is_approximate: bool
    missing_rate: bool
    active_count: int
    trial_count: int
    paused_count: int
    canceled_count: int


async def subscription_summary(session: AsyncSession, space: Space) -> SubscriptionSummary:
    today = today_in_tz(space.timezone)
    rules = (
        (
            await session.execute(
                select(RecurringRule).where(
                    RecurringRule.space_id == space.id,
                    RecurringRule.kind == RecurringKind.subscription,
                )
            )
        )
        .scalars()
        .all()
    )
    counts = {"active": 0, "trial": 0, "paused": 0, "canceled": 0}
    monthly = Decimal(0)
    approximate = missing = False
    for rule in rules:
        state = rule_status(rule, today)
        counts[state] += 1
        if state not in ("active", "trial") or rule.amount is None:
            continue
        base_amount = rule.amount
        if rule.currency != space.base_currency:
            approximate = True
            rate = await fx.get_rate(session, rule.currency, space.base_currency, today)
            if rate is None:
                missing = True
                continue
            base_amount = rule.amount * rate  # FX-04, rounded once at the end
        monthly += base_amount * MONTHLY_FACTOR[rule.frequency]
    monthly_total = monthly.quantize(CENTS, ROUND_HALF_EVEN)
    return SubscriptionSummary(
        monthly_total=monthly_total,
        yearly_total=(monthly * 12).quantize(CENTS, ROUND_HALF_EVEN),
        currency=space.base_currency,
        is_approximate=approximate,
        missing_rate=missing,
        active_count=counts["active"],
        trial_count=counts["trial"],
        paused_count=counts["paused"],
        canceled_count=counts["canceled"],
    )
