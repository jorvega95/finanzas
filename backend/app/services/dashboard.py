"""Agregados del dashboard. Implementa DSH-01..DSH-05.

Todo en SQL con predicados compartidos (DSH-03): este módulo es EL único
lugar que define qué cuenta como gasto/ingreso. Excluye transfers (TXN-02) y
transacciones-madre MSI (MSI-03); incluye cuotas MSI cargadas en el mes.
Conversión a base con la tasa congelada (FX-03/FX-05).
"""

import calendar
import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.dates import today_in_tz
from app.models.cards import CardStatement, StatementStatus
from app.models.catalogs import Category, PaymentMethod, PaymentMethodType
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus
from app.models.recurring import RecurringRule
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

# FX-05: monto en moneda base con la tasa congelada (1 si ya es la base).
AMOUNT_BASE = Transaction.amount * func.coalesce(Transaction.fx_rate_to_base, 1)


def to_money(value: Decimal | int | None) -> Decimal:
    """GLO-01: resultados monetarios en 2 decimales, ROUND_HALF_EVEN."""
    from decimal import ROUND_HALF_EVEN

    return Decimal(value or 0).quantize(CENT, ROUND_HALF_EVEN)


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    """DSH-01: mes calendario. `month` es 'YYYY-MM'."""
    year, month_number = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, month_number)[1]
    return dt.date(year, month_number, 1), dt.date(year, month_number, last)


def expense_predicates(
    space_id: uuid.UUID, start: dt.date, end: dt.date, today: dt.date
) -> list[ColumnElement[bool]]:
    """DSH-02/03: el único predicado de 'gasto directo' del sistema.

    Excluye transfers (TXN-02), madres MSI (MSI-03) y fechas futuras (TXN-03).
    """
    return [
        Transaction.space_id == space_id,
        Transaction.type == TransactionType.expense,
        Transaction.installment_plan_id.is_(None),
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.date <= today,
    ]


def income_predicates(
    space_id: uuid.UUID, start: dt.date, end: dt.date, today: dt.date
) -> list[ColumnElement[bool]]:
    return [
        Transaction.space_id == space_id,
        Transaction.type == TransactionType.income,
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.date <= today,
    ]


def _msi_quota_query(space_id: uuid.UUID, start: dt.date, end: dt.date) -> Any:
    """DSH-02/MSI-03: cuotas MSI cargadas en el periodo, con la categoría y
    naturaleza heredadas de la compra original y su tasa congelada."""
    parent = aliased(Transaction)
    return (
        select(
            (Installment.amount * func.coalesce(parent.fx_rate_to_base, 1)).label("amount_base"),
            parent.category_id.label("category_id"),
            parent.expense_nature_override.label("expense_nature_override"),
            parent.payment_method_id.label("payment_method_id"),
        )
        .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
        .join(parent, InstallmentPlan.transaction_id == parent.id)
        .join(CardStatement, Installment.statement_id == CardStatement.id)
        .where(
            InstallmentPlan.space_id == space_id,
            Installment.status.in_([InstallmentStatus.charged, InstallmentStatus.paid]),
            CardStatement.period_end >= start,
            CardStatement.period_end <= end,
        )
    )


async def _msi_total(
    session: AsyncSession, space_id: uuid.UUID, start: dt.date, end: dt.date
) -> Decimal:
    sub = _msi_quota_query(space_id, start, end).subquery()
    total = await session.scalar(select(func.coalesce(func.sum(sub.c.amount_base), 0)))
    return to_money(total)


async def monthly_totals(
    session: AsyncSession, space: Space, start: dt.date, end: dt.date
) -> dict[str, Decimal]:
    """DSH-02: ingresos, gastos (directos + cuotas MSI) y neto, en base."""
    today = today_in_tz(space.timezone)
    income = await session.scalar(
        select(func.coalesce(func.sum(AMOUNT_BASE), 0)).where(
            *income_predicates(space.id, start, end, today)
        )
    )
    direct_expense = await session.scalar(
        select(func.coalesce(func.sum(AMOUNT_BASE), 0)).where(
            *expense_predicates(space.id, start, end, today)
        )
    )
    msi = await _msi_total(session, space.id, start, end)
    income_total = to_money(income)
    expense_total = to_money(direct_expense) + msi
    return {
        "income": income_total,
        "expenses": expense_total,
        "net": income_total - expense_total,
    }


async def cash_flow_totals(
    session: AsyncSession, space: Space, start: dt.date, end: dt.date
) -> dict[str, Decimal]:
    """DSH-04 vista flujo: sale el dinero cuando se paga, no cuando se compra.

    Salidas = gastos no diferidos (efectivo, débito y prepaid salen en su
    fecha, TAR-04) + pagos de tarjeta de crédito (transfers hacia métodos
    credit_card, TDC-10/TXN-06). Los cargos de crédito se difieren: solo entran
    como flujo cuando se paga el statement. Entradas = income.
    """
    today = today_in_tz(space.timezone)
    income = await session.scalar(
        select(func.coalesce(func.sum(AMOUNT_BASE), 0)).where(
            *income_predicates(space.id, start, end, today)
        )
    )
    non_card_expense = await session.scalar(
        select(func.coalesce(func.sum(AMOUNT_BASE), 0)).where(
            *expense_predicates(space.id, start, end, today),
            # TAR-04: only credit charges carry a statement and are deferred;
            # debit/prepaid/cash spend has no statement and is immediate.
            Transaction.statement_id.is_(None),
        )
    )
    card_payments = await session.scalar(
        select(func.coalesce(func.sum(AMOUNT_BASE), 0))
        .select_from(Transaction)
        .join(PaymentMethod, Transaction.payment_method_to_id == PaymentMethod.id)
        .where(
            Transaction.space_id == space.id,
            Transaction.type == TransactionType.transfer,
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.date <= today,
            PaymentMethod.type == PaymentMethodType.credit_card,
        )
    )
    out_total = to_money(non_card_expense) + to_money(card_payments)
    income_total = to_money(income)
    return {"income": income_total, "expenses": out_total, "net": income_total - out_total}


async def expenses_by_category(
    session: AsyncSession, space: Space, start: dt.date, end: dt.date
) -> list[dict[str, Any]]:
    """DSH-03 + CAT-06: agrega por categoría raíz (subcategorías suman al
    padre); incluye cuotas MSI con la categoría de la compra."""
    today = today_in_tz(space.timezone)
    rows = (
        await session.execute(
            select(Transaction.category_id, func.sum(AMOUNT_BASE).label("total"))
            .where(*expense_predicates(space.id, start, end, today))
            .group_by(Transaction.category_id)
        )
    ).all()
    sub = _msi_quota_query(space.id, start, end).subquery()
    msi_rows = (
        await session.execute(
            select(sub.c.category_id, func.sum(sub.c.amount_base)).group_by(sub.c.category_id)
        )
    ).all()

    categories = {
        c.id: c
        for c in (
            (await session.execute(select(Category).where(Category.space_id == space.id)))
            .scalars()
            .all()
        )
    }
    buckets: dict[uuid.UUID | None, Decimal] = {}
    for category_id, total in list(rows) + list(msi_rows):
        category = categories.get(category_id)
        root_id = category.parent_id or category.id if category else None
        buckets[root_id] = buckets.get(root_id, ZERO) + to_money(total)

    result = []
    for root_id, total in buckets.items():
        root = categories.get(root_id) if root_id else None
        result.append(
            {
                "category_id": root_id,
                "category_name": root.name if root else "Sin categoría",
                "total": total,
            }
        )
    return sorted(result, key=lambda r: r["total"], reverse=True)


async def expenses_by_nature(
    session: AsyncSession, space: Space, start: dt.date, end: dt.date
) -> dict[str, Decimal]:
    """DSH-03 + CAT-03: por naturaleza con COALESCE(override, categoría)."""
    today = today_in_tz(space.timezone)
    nature = func.coalesce(Transaction.expense_nature_override, Category.expense_nature)
    rows = (
        await session.execute(
            select(nature.label("nature"), func.sum(AMOUNT_BASE))
            .join(Category, Transaction.category_id == Category.id)
            .where(*expense_predicates(space.id, start, end, today))
            .group_by(nature)
        )
    ).all()

    parent_txn = aliased(Transaction)
    parent_cat = aliased(Category)
    msi_nature = func.coalesce(parent_txn.expense_nature_override, parent_cat.expense_nature)
    msi_rows = (
        await session.execute(
            select(
                msi_nature.label("nature"),
                func.sum(Installment.amount * func.coalesce(parent_txn.fx_rate_to_base, 1)),
            )
            .select_from(Installment)
            .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
            .join(parent_txn, InstallmentPlan.transaction_id == parent_txn.id)
            .join(parent_cat, parent_txn.category_id == parent_cat.id)
            .join(CardStatement, Installment.statement_id == CardStatement.id)
            .where(
                InstallmentPlan.space_id == space.id,
                Installment.status.in_([InstallmentStatus.charged, InstallmentStatus.paid]),
                CardStatement.period_end >= start,
                CardStatement.period_end <= end,
            )
            .group_by(msi_nature)
        )
    ).all()

    result: dict[str, Decimal] = {}
    for nature_value, total in list(rows) + list(msi_rows):
        key = str(
            nature_value.value if hasattr(nature_value, "value") else nature_value or "variable"
        )
        result[key] = result.get(key, ZERO) + to_money(total)
    return result


async def trend(
    session: AsyncSession, space: Space, month: str, months_back: int = 6
) -> list[dict[str, Any]]:
    """DSH-03: tendencia de N meses con los MISMOS predicados de DSH-02."""
    year, month_number = int(month[:4]), int(month[5:7])
    points = []
    for _ in range(months_back):
        key = f"{year:04d}-{month_number:02d}"
        start, end = month_bounds(key)
        totals = await monthly_totals(session, space, start, end)
        points.append({"month": key, **totals})
        month_number -= 1
        if month_number == 0:
            month_number, year = 12, year - 1
    return list(reversed(points))


async def upcoming_commitments(
    session: AsyncSession, space: Space, limit: int = 10
) -> list[dict[str, Any]]:
    """DSH-05: statements por vencer, cuotas MSI próximas y recurrentes."""
    from app.services.recurring import occurrences

    today = today_in_tz(space.timezone)
    horizon = today + dt.timedelta(days=45)
    items: list[dict[str, Any]] = []

    statements = (
        (
            await session.execute(
                select(CardStatement).where(
                    CardStatement.space_id == space.id,
                    CardStatement.status.in_(
                        [StatementStatus.closed, StatementStatus.partially_paid]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for st in statements:
        amount = st.computed_total - st.paid_amount
        if amount > 0:
            items.append(
                {
                    "kind": "card_due",
                    "date": st.due_date,
                    "description": "Pago de tarjeta",
                    "amount": amount,
                    "ref_id": st.id,
                    "is_overdue": today > st.due_date,
                }
            )

    quotas = (
        await session.execute(
            select(Installment, Transaction.description)
            .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
            .join(Transaction, InstallmentPlan.transaction_id == Transaction.id)
            .where(
                InstallmentPlan.space_id == space.id,
                Installment.status == InstallmentStatus.pending,
                Installment.estimated_charge_date <= horizon,
            )
        )
    ).all()
    for installment, description in quotas:
        items.append(
            {
                "kind": "msi_quota",
                "date": installment.estimated_charge_date,
                "description": f"MSI: {description}",
                "amount": installment.amount,
                "ref_id": installment.id,
                "is_overdue": False,
            }
        )

    rules = (
        (
            await session.execute(
                select(RecurringRule).where(
                    RecurringRule.space_id == space.id,
                    RecurringRule.is_active.is_(True),
                    RecurringRule.type == TransactionType.expense,
                )
            )
        )
        .scalars()
        .all()
    )
    for rule in rules:
        upcoming = [d for d in occurrences(rule, horizon) if d > today]
        if upcoming:
            items.append(
                {
                    "kind": "recurring",
                    "date": upcoming[0],
                    "description": rule.description,
                    "amount": rule.amount,
                    "ref_id": rule.id,
                    "is_overdue": False,
                }
            )

    items.sort(key=lambda item: item["date"])
    return items[:limit]
