"""Presupuestos. Implementa PRE-01..PRE-04.

Consumo: mismos predicados que DSH-02 (services/dashboard.py es el único
dueño de la definición de "gasto"), restringidos a una categoría raíz y sus
subcategorías (CAT-06).
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.budgets import Budget
from app.models.catalogs import Category, CategoryKind
from app.models.reminders import Reminder, ReminderChannel, ReminderKind
from app.models.spaces import Space
from app.models.transactions import Transaction
from app.services.dashboard import AMOUNT_BASE, _msi_quota_query, expense_predicates, to_money

ZERO = Decimal("0.00")


def parse_month(month: str) -> dt.date:
    try:
        return dt.date(int(month[:4]), int(month[5:7]), 1)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mes inválido (YYYY-MM)") from exc


async def _category_tree_ids(
    session: AsyncSession, space_id: uuid.UUID, root_id: uuid.UUID
) -> list[uuid.UUID]:
    """PRE-02/CAT-06: la raíz y sus subcategorías (máx. 2 niveles)."""
    children = (
        (
            await session.execute(
                select(Category.id).where(
                    Category.space_id == space_id, Category.parent_id == root_id
                )
            )
        )
        .scalars()
        .all()
    )
    return [root_id, *children]


async def budget_consumption(session: AsyncSession, space: Space, budget: Budget) -> Decimal:
    """PRE-02: gastos del mes de la categoría (y subcategorías) en base,
    incluyendo cuotas MSI cargadas ese mes; transfers y madres MSI fuera
    (vía expense_predicates de DSH-02)."""
    import calendar

    start = budget.month
    end = dt.date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    today = today_in_tz(space.timezone)
    category_ids = await _category_tree_ids(session, space.id, budget.category_id)

    direct = await session.scalar(
        select(func.coalesce(func.sum(AMOUNT_BASE), 0)).where(
            *expense_predicates(space.id, start, end, today),
            Transaction.category_id.in_(category_ids),
        )
    )
    sub = _msi_quota_query(space.id, start, end).subquery()
    msi = await session.scalar(
        select(func.coalesce(func.sum(sub.c.amount_base), 0)).where(
            sub.c.category_id.in_(category_ids)
        )
    )
    return to_money(direct) + to_money(msi)


async def get_budget(session: AsyncSession, space_id: uuid.UUID, budget_id: uuid.UUID) -> Budget:
    budget = await session.get(Budget, budget_id)
    if budget is None or budget.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Presupuesto no encontrado")
    return budget


async def create_budget(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    category_id: uuid.UUID,
    month: dt.date,
    amount: Decimal,
    alert_threshold: Decimal = Decimal("0.80"),
) -> Budget:
    """PRE-01: único por categoría raíz + mes."""
    category = await session.get(Category, category_id)
    if category is None or category.space_id != space.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoría no encontrada")
    if category.kind != CategoryKind.expense or category.parent_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El presupuesto aplica a categorías raíz de gasto",
        )
    duplicate = await session.scalar(
        select(Budget.id).where(
            Budget.space_id == space.id,
            Budget.category_id == category_id,
            Budget.month == month,
        )
    )
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe presupuesto para ese mes")
    budget = Budget(
        space_id=space.id,
        category_id=category_id,
        month=month,
        amount=amount,
        alert_threshold=alert_threshold,
        created_by=created_by,
    )
    session.add(budget)
    await session.commit()
    await session.refresh(budget)
    return budget


async def copy_budgets(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    from_month: dt.date,
    to_month: dt.date,
) -> int:
    """PRE-01: "repetir presupuestos" del mes anterior en bloque."""
    source = (
        (
            await session.execute(
                select(Budget).where(Budget.space_id == space.id, Budget.month == from_month)
            )
        )
        .scalars()
        .all()
    )
    existing = {
        row
        for row in (
            await session.execute(
                select(Budget.category_id).where(
                    Budget.space_id == space.id, Budget.month == to_month
                )
            )
        ).scalars()
    }
    copied = 0
    for budget in source:
        if budget.category_id in existing:
            continue
        session.add(
            Budget(
                space_id=space.id,
                category_id=budget.category_id,
                month=to_month,
                amount=budget.amount,
                alert_threshold=budget.alert_threshold,
                created_by=created_by,
            )
        )
        copied += 1
    await session.commit()
    return copied


async def check_budget_alerts(session: AsyncSession, space: Space, month: dt.date) -> int:
    """PRE-03: una sola alerta al cruzar el umbral y una al cruzar 100%, por
    presupuesto-mes. Reusa reminders (REM-04) con unicidad por
    (kind, ref_id=budget, offset_days=nivel, canal)."""
    budgets = (
        (
            await session.execute(
                select(Budget).where(Budget.space_id == space.id, Budget.month == month)
            )
        )
        .scalars()
        .all()
    )
    created = 0
    today = today_in_tz(space.timezone)
    for budget in budgets:
        consumed = await budget_consumption(session, space, budget)
        ratio = consumed / budget.amount if budget.amount else ZERO
        category = await session.get(Category, budget.category_id)
        name = category.name if category else "Categoría"
        levels = []
        if ratio >= 1:
            levels.append((100, f"Presupuesto de {name} superado: {consumed} de {budget.amount}"))
        if ratio >= budget.alert_threshold:
            percent = int(budget.alert_threshold * 100)
            levels.append(
                (
                    percent,
                    f"Presupuesto de {name} al {int(ratio * 100)}% ({consumed} de {budget.amount})",
                )
            )
        for level, message in levels:
            for channel in (ReminderChannel.in_app, ReminderChannel.email):
                duplicate = await session.scalar(
                    select(Reminder.id).where(
                        Reminder.kind == ReminderKind.budget_alert,
                        Reminder.ref_id == budget.id,
                        Reminder.offset_days == level,
                        Reminder.channel == channel,
                    )
                )
                if duplicate is None:
                    session.add(
                        Reminder(
                            space_id=space.id,
                            kind=ReminderKind.budget_alert,
                            ref_id=budget.id,
                            offset_days=level,
                            fire_at=today,
                            channel=channel,
                            message=message,
                        )
                    )
                    created += 1
    await session.commit()
    return created


async def budgets_with_progress(
    session: AsyncSession, space: Space, month: dt.date
) -> list[dict[str, Any]]:
    """PRE-04: presupuesto vs consumido (variación) por categoría."""
    budgets = (
        await session.execute(
            select(Budget, Category.name)
            .join(Category, Budget.category_id == Category.id)
            .where(Budget.space_id == space.id, Budget.month == month)
            .order_by(Category.name)
        )
    ).all()
    result = []
    for budget, category_name in budgets:
        consumed = await budget_consumption(session, space, budget)
        result.append(
            {
                "budget": budget,
                "category_name": category_name,
                "consumed": consumed,
                "remaining": budget.amount - consumed,
            }
        )
    return result
