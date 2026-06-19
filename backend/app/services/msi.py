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
    """MSI-04: estimated_charge_date = period_end (día de corte) del ciclo de
    cada cuota, que es cuando el banco imprime el cargo en el estado de cuenta."""
    _, first_cutoff = cycles.cycle_for_purchase(purchase_date, card_spec)
    dates = [first_cutoff]
    cutoff = first_cutoff
    for _ in range(months - 1):
        cutoff = cycles.next_cutoff(cutoff, card_spec)
        dates.append(cutoff)
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

    spec = spec_for(card)
    amounts = split_installments(txn.amount, months)
    charge_dates = installment_charge_dates(txn.date, spec, months)
    old_statement_id = txn.statement_id

    # MSI-05: classify each installment by its cycle relative to today.
    # charge_date < current_cutoff → past closed cycle → paid.
    # charge_date == current_cutoff → currently open cycle → charged.
    # charge_date > current_cutoff → future cycle → pending.
    today = _today_for_space(space)
    current_cutoff = cycles.cutoff_on_or_after(today, spec)

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
        if charge_date < current_cutoff:
            # Past cycle: already covered. Cuota 1 keeps old_statement_id so
            # recompute_statement_total reflects the installment instead of the
            # full transaction amount.
            stmt_id = old_statement_id if number == 1 else None
            inst_status = InstallmentStatus.paid
        elif charge_date == current_cutoff:
            # Current open cycle: charge lands here.
            open_stmt = await get_or_create_statement(session, card, charge_date)
            stmt_id = open_stmt.id
            inst_status = InstallmentStatus.charged
        else:
            stmt_id = None
            inst_status = InstallmentStatus.pending

        session.add(
            Installment(
                plan_id=plan.id,
                number=number,
                amount=amount,
                estimated_charge_date=charge_date,
                statement_id=stmt_id,
                status=inst_status,
            )
        )
    # MSI-03: la transacción-madre queda marcada y fuera de agregados; si ya
    # estaba asignada a un statement, se desasigna (las cuotas toman su lugar).
    txn.installment_plan_id = plan.id
    txn.statement_id = None
    await session.flush()
    # If every installment is in the past, the plan is completed immediately.
    if charge_dates[-1] < current_cutoff:
        plan.status = PlanStatus.completed
    if old_statement_id is not None:
        await recompute_statement_total(session, old_statement_id)
    await session.commit()
    await session.refresh(plan)
    return plan


def _project_installment_dates(
    current_number: int,
    total_months: int,
    anchor_cutoff: date,
    spec: cycles.CardCycleSpec,
) -> list[date]:
    """Proyecta period_end (día de corte) de cada cuota desde el ciclo ancla.

    Cuota current_number → anchor_cutoff (period_end de su ciclo).
    Cuotas anteriores: itera hacia atrás un corte por cuota.
    Cuotas posteriores: itera hacia adelante un corte por cuota.
    """
    dates: list[date | None] = [None] * total_months
    dates[current_number - 1] = anchor_cutoff

    # Forward: cuotas posteriores a la actual.
    cutoff = anchor_cutoff
    for i in range(current_number, total_months):
        cutoff = cycles.next_cutoff(cutoff, spec)
        dates[i] = cutoff

    # Backward: cuotas anteriores a la actual.
    cutoff = anchor_cutoff
    for i in range(current_number - 2, -1, -1):
        cutoff = cycles.previous_cutoff(cutoff, spec)
        dates[i] = cutoff

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

    current_is_charged=True → cuota N ya está en el opening_balance del corte cerrado
      (no hay que sumarla de nuevo): cuotas 1..N → paid; cuota N+1 → charged asignada
      al statement abierto del ciclo en curso → aparece en Ciclo en curso.
      Caso borde N==M: todas paid, plan status=completed al crearse.
    current_is_charged=False → cuota N se cobrará en el ciclo actualmente abierto:
      cuotas 1..N-1 → paid; cuota N → charged asignada al statement abierto → Ciclo en
      curso; cuotas N+1..M → pending → MSI por venir.
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
    # coa = primer corte >= hoy (puede ser hoy mismo si hoy es día de corte).
    #
    # charged → la cuota ya apareció en el ÚLTIMO estado de cuenta cerrado:
    #   - si hoy es día de corte: ese corte (acaba de cerrar hoy) es el ancla.
    #   - si hoy está entre cortes: el corte anterior (el más recientemente cerrado).
    # pending → la cuota se cobrará en el ciclo ACTUALMENTE ABIERTO:
    #   - si hoy es día de corte: el ciclo que abre mañana (cierra al próximo corte).
    #   - si hoy está entre cortes: el ciclo que cierra en coa.
    coa = cycles.cutoff_on_or_after(today, spec)
    if current_is_charged:
        anchor_cutoff = coa if coa == today else cycles.previous_cutoff(coa, spec)
    else:
        anchor_cutoff = cycles.next_cutoff(coa, spec) if coa == today else coa

    charge_dates = _project_installment_dates(
        current_number=current_number,
        total_months=total_months,
        anchor_cutoff=anchor_cutoff,
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

    # Cuota que corresponde al ciclo en curso (la que entra en Ciclo en curso).
    # charged=True → cuota N ya está en opening_balance (paid); la activa en el ciclo es N+1.
    # charged=False → la activa en el ciclo es N.
    active_number = current_number + 1 if current_is_charged else current_number

    installments_created: list[Installment] = []
    for number, (inst_amount, charge_date) in enumerate(
        zip(amounts, charge_dates, strict=True), start=1
    ):
        if current_is_charged:
            # Cuotas 1..N → paid (N ya viene en opening_balance); N+1 se ajusta después.
            inst_status = (
                InstallmentStatus.paid if number <= current_number else InstallmentStatus.pending
            )
        else:
            # Cuotas 1..N-1 → paid; N se ajusta después; N+1..M → pending.
            inst_status = (
                InstallmentStatus.paid if number < current_number else InstallmentStatus.pending
            )
        inst = Installment(
            plan_id=plan.id,
            number=number,
            amount=inst_amount,
            estimated_charge_date=charge_date,
            status=inst_status,
        )
        session.add(inst)
        installments_created.append(inst)

    await session.flush()

    if active_number <= total_months:
        # Asignar la cuota activa al statement abierto del ciclo en curso.
        active_inst = installments_created[active_number - 1]
        active_cutoff = charge_dates[active_number - 1]
        open_stmt = await get_or_create_statement(session, card, active_cutoff)
        active_inst.statement_id = open_stmt.id
        active_inst.status = InstallmentStatus.charged
    elif current_is_charged:
        # N == M y charged=True: todas las cuotas quedan paid → plan completado.
        plan.status = PlanStatus.completed

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
