"""Transacciones recurrentes. Implementa REC-01..REC-05.

Idempotencia por (recurring_rule_id, scheduled_date) — constraint único.
"""

import calendar
import uuid
from collections.abc import Iterator
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.catalogs import Category, PaymentMethod
from app.models.recurring import RecurringFrequency, RecurringRule, RecurringTombstone
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services.transactions import TransactionInput, create_transaction


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
    elif rule.frequency == RecurringFrequency.monthly:
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
            month += 1
            if month == 13:
                month, year = 1, year + 1
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
                )
            )
        )
        .scalars()
        .all()
    )
    for rule in rules:
        # REC-04: rules pointing at deactivated catalog entries auto-pause.
        category = await session.get(Category, rule.category_id) if rule.category_id else None
        method = (
            await session.get(PaymentMethod, rule.payment_method_id)
            if rule.payment_method_id
            else None
        )
        if (category is not None and not category.is_active) or (
            method is not None and not method.is_active
        ):
            rule.is_active = False
            await session.commit()
            continue

        existing = {
            row
            for row in (
                await session.execute(
                    select(Transaction.scheduled_date).where(
                        Transaction.recurring_rule_id == rule.id
                    )
                )
            ).scalars()
        }
        tombstones = {
            row
            for row in (
                await session.execute(
                    select(RecurringTombstone.scheduled_date).where(
                        RecurringTombstone.rule_id == rule.id
                    )
                )
            ).scalars()
        }
        for scheduled in occurrences(rule, today):
            if scheduled in existing or scheduled in tombstones:
                continue
            await create_transaction(
                session,
                space,
                rule.created_by,
                TransactionInput(
                    type=rule.type,
                    date=scheduled,
                    amount=rule.amount,
                    currency=rule.currency,
                    description=rule.description,
                    category_id=rule.category_id,
                    payment_method_id=rule.payment_method_id,
                ),
                recurring_rule_id=rule.id,
                scheduled_date=scheduled,
                needs_review=True,  # REC-03: born pending review.
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
    if frequency == RecurringFrequency.monthly and not use_last_day:
        return month_day or start_date.day
    return None if use_last_day or frequency != RecurringFrequency.monthly else month_day
