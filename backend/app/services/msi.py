"""Planes MSI. Implementa MSI-01..MSI-09.

Invariante MSI-02 (test property-based obligatorio): sum(cuotas) == total exacto.
"""

import uuid
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalogs import CardBehavior
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus, PlanStatus
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import billing_cycles as cycles
from app.services.cards import (
    card_behavior,
    get_card,
    get_or_create_statement,
    recompute_statement_total,
    spec_for,
)

CENT = Decimal("0.01")


def split_installments(total: Decimal, months: int) -> list[Decimal]:
    """MSI-02: monthly = ROUND_FLOOR(total/months, 2); última cuota absorbe
    el residuo. Invariante: Σ cuotas == total exacto."""
    monthly = (total / months).quantize(CENT, ROUND_FLOOR)
    last = total - monthly * (months - 1)
    return [monthly] * (months - 1) + [last]


def installment_charge_dates(
    purchase_date: date, card_spec: cycles.CardCycleSpec, months: int
) -> list[date]:
    """MSI-04: estimated_charge_date = max(purchase_date, period_start) del
    ciclo de cada cuota. La cuota 1 siempre cae en purchase_date (period_start
    <= purchase_date por construcción de TDC-05); las cuotas 2..n en el
    period_start de su ciclo."""
    first_start, first_cutoff = cycles.cycle_for_purchase(purchase_date, card_spec)
    dates = [max(purchase_date, first_start)]
    current_cutoff = first_cutoff
    for _ in range(months - 1):
        next_cut = cycles.next_cutoff(current_cutoff, card_spec)
        start, current_cutoff = cycles.cycle_for_cutoff(next_cut, card_spec)
        dates.append(max(purchase_date, start))
    return dates


async def get_plan(
    session: AsyncSession, space_id: uuid.UUID, plan_id: uuid.UUID
) -> InstallmentPlan:
    plan = await session.get(
        InstallmentPlan, plan_id, options=[selectinload(InstallmentPlan.installments)]
    )
    if plan is None or plan.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan MSI no encontrado")
    return plan


async def create_plan_from_transaction(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    transaction_id: uuid.UUID,
    months: int,
) -> InstallmentPlan:
    """MSI-01: convierte una compra expense con TDC en plan MSI (también IMP-05)."""
    txn = await session.get(Transaction, transaction_id)
    if txn is None or txn.space_id != space.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transacción no encontrada")
    if txn.type != TransactionType.expense or txn.card_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "MSI solo aplica a compras con tarjeta de crédito",
        )
    if txn.installment_plan_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "La compra ya tiene plan MSI")
    if not 2 <= months <= 60:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Meses fuera de rango [2, 60]")
    if txn.amount < CENT * months:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Monto demasiado pequeño")

    card = await get_card(session, space.id, txn.card_id)
    # MSI-01/TAR-02: MSI only exists on credit cards.
    if await card_behavior(session, card) != CardBehavior.credit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "MSI solo aplica a tarjetas de crédito",
        )
    # MSI-09: compra en moneda distinta a la de la tarjeta no soportada en v1.
    if txn.currency != card.currency:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Compras MSI en moneda distinta a la de la tarjeta no se soportan",
        )

    amounts = split_installments(txn.amount, months)
    charge_dates = installment_charge_dates(txn.date, spec_for(card), months)

    plan = InstallmentPlan(
        space_id=space.id,
        credit_card_id=card.id,
        transaction_id=txn.id,
        total_amount=txn.amount,
        months=months,
        monthly_amount=amounts[0],
        start_date=txn.date,
        created_by=created_by,
    )
    session.add(plan)
    await session.flush()
    for number, (amount, charge_date) in enumerate(
        zip(amounts, charge_dates, strict=True), start=1
    ):
        session.add(
            Installment(
                plan_id=plan.id,
                number=number,
                amount=amount,
                estimated_charge_date=charge_date,
            )
        )
    # MSI-03: la transacción-madre queda marcada y fuera de agregados; si ya
    # estaba asignada a un statement, se desasigna (las cuotas toman su lugar).
    txn.installment_plan_id = plan.id
    old_statement_id = txn.statement_id
    txn.statement_id = None
    await session.flush()
    if old_statement_id is not None:
        await recompute_statement_total(session, old_statement_id)
    await session.commit()
    await session.refresh(plan)
    return plan


async def create_plan_backfill(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    description: str,
    amount: Decimal,
    currency: str,
    card_id: uuid.UUID,
    purchase_date: date,
    months: int,
    category_id: uuid.UUID,
) -> InstallmentPlan:
    """MSI-10: crea un plan MSI retroactivo sin transacción previa.

    Las cuotas con estimated_charge_date <= hoy quedan paid (ya se pagaron);
    las futuras quedan pending. Ninguna cuota retroactiva se asigna a statement.
    """
    if not 2 <= months <= 60:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Meses fuera de rango [2, 60]")
    if amount < CENT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Monto inválido")
    if amount < CENT * months:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Monto demasiado pequeño para el número de meses",
        )

    card = await get_card(session, space.id, card_id)
    if currency != card.currency:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Compras MSI en moneda distinta a la de la tarjeta no se soportan",
        )
    if card.payment_method_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "La tarjeta no tiene método de pago asociado",
        )

    today = _today_for_space(space)
    amounts = split_installments(amount, months)
    charge_dates = installment_charge_dates(purchase_date, spec_for(card), months)

    txn = Transaction(
        space_id=space.id,
        type=TransactionType.expense,
        date=purchase_date,
        description=description,
        amount=amount,
        currency=currency,
        category_id=category_id,
        payment_method_id=card.payment_method_id,
        credit_card_id=card.id,
        created_by=created_by,
    )
    session.add(txn)
    await session.flush()

    plan = InstallmentPlan(
        space_id=space.id,
        credit_card_id=card.id,
        transaction_id=txn.id,
        total_amount=amount,
        months=months,
        monthly_amount=amounts[0],
        start_date=purchase_date,
        created_by=created_by,
    )
    session.add(plan)
    await session.flush()

    for number, (inst_amount, charge_date) in enumerate(
        zip(amounts, charge_dates, strict=True), start=1
    ):
        inst_status = (
            InstallmentStatus.paid if charge_date <= today else InstallmentStatus.pending
        )
        session.add(
            Installment(
                plan_id=plan.id,
                number=number,
                amount=inst_amount,
                estimated_charge_date=charge_date,
                status=inst_status,
            )
        )

    # MSI-03: la transacción-madre queda excluida de agregados via installment_plan_id.
    txn.installment_plan_id = plan.id
    await session.commit()
    await session.refresh(plan)
    return plan


async def settle_plan_early(
    session: AsyncSession, space: Space, user_id: uuid.UUID, plan_id: uuid.UUID
) -> InstallmentPlan:
    """MSI-07: cancela cuotas pending y genera un cargo único por su suma en
    el statement abierto de la tarjeta. Auditado vía status=settled_early."""
    plan = await get_plan(session, space.id, plan_id)
    if plan.status != PlanStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "El plan no está activo")

    pending = [i for i in plan.installments if i.status == InstallmentStatus.pending]
    if not pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "No hay cuotas pendientes")
    total_pending = sum((i.amount for i in pending), Decimal("0"))

    card = await get_card(session, space.id, plan.credit_card_id)
    purchase = await session.get(Transaction, plan.transaction_id)
    assert purchase is not None
    spec = spec_for(card)
    # Cargo único en el statement abierto actual de la tarjeta.
    settlement = Transaction(
        space_id=space.id,
        type=TransactionType.expense,
        date=_today_for_space(space),
        description=f"Liquidación MSI: {purchase.description}",
        amount=Decimal(total_pending),
        currency=purchase.currency,
        category_id=purchase.category_id,
        payment_method_id=purchase.payment_method_id,
        card_id=card.id,
        created_by=user_id,
    )
    session.add(settlement)
    await session.flush()
    statement = await get_or_create_statement(
        session, card, cycles.cycle_for_purchase(settlement.date, spec)[1]
    )
    settlement.statement_id = statement.id

    for installment in pending:
        installment.status = InstallmentStatus.canceled
    plan.status = PlanStatus.settled_early
    await session.commit()
    await session.refresh(plan)
    return plan


def _today_for_space(space: Space) -> date:
    from app.core.dates import today_in_tz

    return today_in_tz(space.timezone)


async def delete_plan_if_allowed(session: AsyncSession, plan: InstallmentPlan) -> None:
    """MSI-08: borrar la compra borra el plan solo si todas las cuotas están
    pending; si no, se bloquea."""
    non_pending = [i for i in plan.installments if i.status not in (InstallmentStatus.pending,)]
    if non_pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El plan tiene cuotas cargadas o pagadas; liquida o ajusta en su lugar",
        )
    await session.delete(plan)


async def plans_summary(session: AsyncSession, space_id: uuid.UUID) -> list[dict[str, Any]]:
    """MSI-06 por plan: cuotas pagadas/cargadas/restantes, monto restante,
    fecha de liquidación proyectada."""
    plans = (
        (
            await session.execute(
                select(InstallmentPlan)
                .options(selectinload(InstallmentPlan.installments))
                .where(InstallmentPlan.space_id == space_id)
                .order_by(InstallmentPlan.start_date.desc())
            )
        )
        .scalars()
        .unique()
        .all()
    )
    result = []
    for plan in plans:
        installments = plan.installments
        paid = [i for i in installments if i.status == InstallmentStatus.paid]
        charged = [i for i in installments if i.status == InstallmentStatus.charged]
        pending = [i for i in installments if i.status == InstallmentStatus.pending]
        remaining = sum(
            (
                i.amount
                for i in installments
                if i.status not in (InstallmentStatus.paid, InstallmentStatus.canceled)
            ),
            Decimal("0.00"),
        )
        result.append(
            {
                "plan": plan,
                "paid_count": len(paid),
                "charged_count": len(charged),
                "pending_count": len(pending),
                "remaining_amount": remaining,
                "projected_payoff": max(
                    (i.estimated_charge_date for i in installments), default=plan.start_date
                ),
            }
        )
    return result


async def monthly_projection(session: AsyncSession, space_id: uuid.UUID) -> list[dict[str, Any]]:
    """MSI-06 global: total comprometido por mes futuro × tarjeta (cuotas
    pending por estimated_charge_date)."""
    rows = await session.execute(
        select(
            InstallmentPlan.credit_card_id,
            Installment.estimated_charge_date,
            Installment.amount,
        )
        .join(Installment, Installment.plan_id == InstallmentPlan.id)
        .where(
            InstallmentPlan.space_id == space_id,
            Installment.status == InstallmentStatus.pending,
        )
    )
    buckets: dict[tuple[uuid.UUID, str], Decimal] = {}
    for card_id, charge_date, amount in rows.all():
        key = (card_id, charge_date.strftime("%Y-%m"))
        buckets[key] = buckets.get(key, Decimal("0")) + amount
    return [
        {"credit_card_id": card_id, "month": month, "amount": amount}
        for (card_id, month), amount in sorted(buckets.items(), key=lambda kv: kv[0][1])
    ]
