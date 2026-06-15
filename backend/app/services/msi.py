"""Planes MSI. Implementa MSI-01..MSI-10.

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
    # MSI-05: si la compra ya estaba en un statement (ciclo actual o pasado),
    # la cuota 1 hereda ese statement y queda charged de inmediato.
    old_statement_id = txn.statement_id

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
        is_first = number == 1 and old_statement_id is not None
        session.add(
            Installment(
                plan_id=plan.id,
                number=number,
                amount=amount,
                estimated_charge_date=charge_date,
                statement_id=old_statement_id if is_first else None,
                status=InstallmentStatus.charged if is_first else InstallmentStatus.pending,
            )
        )
    # MSI-03: la transacción-madre queda marcada y fuera de agregados; si ya
    # estaba asignada a un statement, se desasigna (las cuotas toman su lugar).
    txn.installment_plan_id = plan.id
    txn.statement_id = None
    await session.flush()
    if old_statement_id is not None:
        await recompute_statement_total(session, old_statement_id)
    await session.commit()
    await session.refresh(plan)
    return plan


def _project_installment_dates(
    current_number: int,
    total_months: int,
    anchor_cutoff: date,
    anchor_start: date,
    spec: cycles.CardCycleSpec,
) -> list[date]:
    """Proyecta estimated_charge_dates para todas las cuotas desde el ciclo ancla.

    Cuota current_number → anchor_start (period_start de su ciclo).
    Cuotas anteriores: se itera hacia atrás un ciclo por cuota.
    Cuotas posteriores: se itera hacia adelante un ciclo por cuota.
    """
    dates: list[date | None] = [None] * total_months
    dates[current_number - 1] = anchor_start

    # Forward: cuotas posteriores a la actual.
    cutoff = anchor_cutoff
    for i in range(current_number, total_months):
        next_cut = cycles.next_cutoff(cutoff, spec)
        start, cutoff = cycles.cycle_for_cutoff(next_cut, spec)
        dates[i] = start

    # Backward: cuotas anteriores a la actual.
    cutoff = anchor_cutoff
    for i in range(current_number - 2, -1, -1):
        prev_cut = cycles.previous_cutoff(cutoff, spec)
        start, cutoff = cycles.cycle_for_cutoff(prev_cut, spec)
        dates[i] = start

    return dates  # type: ignore[return-value]


async def create_plan_from_current_installment(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    description: str,
    monthly_amount: Decimal,
    currency: str,
    card_id: uuid.UUID,
    category_id: uuid.UUID,
    current_number: int,
    total_months: int,
    current_is_charged: bool,
) -> InstallmentPlan:
    """MSI-10: registra compra MSI anterior al sistema partiendo de la cuota en curso.

    Cuotas 1..N-1 → paid; cuota N → charged/pending según current_is_charged;
    cuotas N+1..M → pending. Las fechas se proyectan con el corte vigente de la tarjeta.
    """
    if not 2 <= total_months <= 60:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Meses fuera de rango [2, 60]")
    if not 1 <= current_number <= total_months:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El número de cuota actual debe estar entre 1 y el total de meses",
        )
    if monthly_amount < CENT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Monto inválido")

    card = await get_card(session, space.id, card_id)
    if await card_behavior(session, card) != CardBehavior.credit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "MSI solo aplica a tarjetas de crédito",
        )
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

    spec = spec_for(card)
    today = _today_for_space(space)

    # Determina el corte ancla de la cuota actual.
    # coa = el corte que CIERRA el ciclo actual (period_end del ciclo en curso).
    # charged → ancla en el ciclo actual (el que el usuario ve en su estado de cuenta).
    # pending → ancla en el siguiente ciclo (el cargo aún no ha aparecido).
    coa = cycles.cutoff_on_or_after(today, spec)
    if current_is_charged:
        anchor_cutoff = coa
    else:
        anchor_cutoff = cycles.next_cutoff(coa, spec)

    anchor_start = cycles.cycle_for_cutoff(anchor_cutoff, spec)[0]
    charge_dates = _project_installment_dates(
        current_number=current_number,
        total_months=total_months,
        anchor_cutoff=anchor_cutoff,
        anchor_start=anchor_start,
        spec=spec,
    )

    # MSI-02: total_amount = monthly × total; split absorbe residuo en última cuota.
    total_amount = (monthly_amount * total_months).quantize(CENT)
    amounts = split_installments(total_amount, total_months)

    txn_date = charge_dates[0]  # fecha estimada de la primera cuota como proxy de la compra
    txn = Transaction(
        space_id=space.id,
        type=TransactionType.expense,
        date=txn_date,
        description=description,
        amount=total_amount,
        currency=currency,
        category_id=category_id,
        payment_method_id=card.payment_method_id,
        card_id=card.id,
        created_by=created_by,
    )
    session.add(txn)
    await session.flush()

    plan = InstallmentPlan(
        space_id=space.id,
        credit_card_id=card.id,
        transaction_id=txn.id,
        total_amount=total_amount,
        months=total_months,
        monthly_amount=amounts[0],
        start_date=txn_date,
        created_by=created_by,
    )
    session.add(plan)
    await session.flush()

    for number, (inst_amount, charge_date) in enumerate(
        zip(amounts, charge_dates, strict=True), start=1
    ):
        if number < current_number:
            inst_status = InstallmentStatus.paid
        elif number == current_number:
            inst_status = InstallmentStatus.charged if current_is_charged else InstallmentStatus.pending
        else:
            inst_status = InstallmentStatus.pending
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
    """MSI-08: borrar la compra borra el plan solo si ninguna cuota está en un
    corte cerrado. Una cuota charged en statement OPEN todavía puede cancelarse
    (el cargo aún no está impreso); si el corte ya cerró o la cuota está paid,
    se bloquea."""
    from app.models.cards import CardStatement, StatementStatus

    for inst in plan.installments:
        if inst.status == InstallmentStatus.paid:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "El plan tiene cuotas pagadas; liquida o ajusta en su lugar",
            )
        if inst.status == InstallmentStatus.charged and inst.statement_id is not None:
            stmt = await session.get(CardStatement, inst.statement_id)
            if stmt is not None and stmt.status != StatementStatus.open:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "El plan tiene cuotas en un corte cerrado; liquida o ajusta en su lugar",
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
