"""Credit cards and statements. Implements TDC-01..TDC-12, MSI-05, REM-01.

The pure cycle math lives in services/billing_cycles.py; this module owns
persistence: cards, statement materialization (TDC-11), charge assignment
(TDC-05/TXN-06), closing (TDC-07), payments (TDC-10) and debt (TDC-09).
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.core.text import normalize_name
from app.models.cards import CardStatement, CreditCard, StatementStatus
from app.models.catalogs import (
    Category,
    CategoryKind,
    ExpenseNature,
    PaymentMethod,
    PaymentMethodType,
)
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus, PlanStatus
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import billing_cycles as cycles

ZERO = Decimal("0.00")
FEES_CATEGORY_NAME = "Comisiones e intereses"  # TDC-13


def spec_for(card: CreditCard) -> cycles.CardCycleSpec:
    return cycles.CardCycleSpec(
        statement_day="last" if card.statement_day_is_last else (card.statement_day or 1),
        cutoff_day_policy=card.cutoff_day_policy.value,
        payment_due_days=card.payment_due_days,
        payment_day="last"
        if card.payment_day_is_last
        else card.payment_day
        if card.payment_day is not None
        else None,
    )


async def get_card(session: AsyncSession, space_id: uuid.UUID, card_id: uuid.UUID) -> CreditCard:
    card = await session.get(CreditCard, card_id)
    if card is None or card.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tarjeta no encontrada")
    return card


async def _ensure_fees_category(
    session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID
) -> None:
    """TDC-13: seed 'Comisiones e intereses' with the first card."""
    normalized = normalize_name(FEES_CATEGORY_NAME)
    exists_already = await session.scalar(
        select(Category.id).where(
            Category.space_id == space_id,
            Category.kind == CategoryKind.expense,
            Category.name_normalized == normalized,
        )
    )
    if exists_already is None:
        session.add(
            Category(
                space_id=space_id,
                name=FEES_CATEGORY_NAME,
                name_normalized=normalized,
                kind=CategoryKind.expense,
                expense_nature=ExpenseNature.fixed,
                created_by=created_by,
            )
        )


async def create_card(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    alias: str,
    bank: str,
    network: str,
    last4: str,
    statement_day: int | str,
    cutoff_day_policy: str = "include",
    payment_due_days: int | None = None,
    payment_day: int | str | None = None,
    credit_limit: Decimal | None = None,
    currency: str = "MXN",
    reminder_days: list[int] | None = None,
    color: str | None = None,
) -> CreditCard:
    """TDC-01 + CAT-07: creates the card and its linked payment method."""
    if not (last4.isdigit() and len(last4) == 4):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "last4 debe ser 4 dígitos")
    if (payment_due_days is None) == (payment_day is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Define exactamente uno: payment_due_days o payment_day",
        )
    if payment_due_days is not None and not 1 <= payment_due_days <= 30:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "payment_due_days fuera de 1-30")
    # Validate day domains via the cycle engine (raises ValueError).
    try:
        cycles.statement_cutoff(statement_day, 2026, 1)
        if payment_day is not None:
            cycles.statement_cutoff(payment_day, 2026, 1)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    card = CreditCard(
        space_id=space.id,
        alias=alias,
        bank=bank,
        network=network,
        last4=last4,
        currency=currency,
        credit_limit=credit_limit,
        statement_day=None if statement_day == "last" else int(statement_day),
        statement_day_is_last=statement_day == "last",
        cutoff_day_policy=cutoff_day_policy,
        payment_due_days=payment_due_days,
        payment_day=int(payment_day)
        if isinstance(payment_day, int | str) and payment_day != "last"
        else None,
        payment_day_is_last=payment_day == "last",
        reminder_days=reminder_days if reminder_days is not None else [3, 1],
        color=color,
        created_by=created_by,
    )
    session.add(card)
    await session.flush()

    # CAT-07: auto-create the linked payment method.
    method = PaymentMethod(
        space_id=space.id,
        name=alias,
        name_normalized=normalize_name(alias),
        type=PaymentMethodType.credit_card,
        credit_card_id=card.id,
        created_by=created_by,
    )
    session.add(method)
    await session.flush()
    card.payment_method_id = method.id
    await _ensure_fees_category(session, space.id, created_by)
    await session.commit()
    await session.refresh(card)
    return card


async def deactivate_card(session: AsyncSession, card: CreditCard) -> None:
    """TDC-12: no new charges, but cycles keep closing until settled."""
    card.is_active = False
    if card.payment_method_id is not None:
        method = await session.get(PaymentMethod, card.payment_method_id)
        if method is not None:
            method.is_active = False  # CAT-07
    await session.commit()


# --- Statements ----------------------------------------------------------------


async def get_or_create_statement(
    session: AsyncSession, card: CreditCard, cutoff: date
) -> CardStatement:
    """TDC-11: statements materialize on demand, never in advance."""
    existing = await session.scalar(
        select(CardStatement).where(
            CardStatement.credit_card_id == card.id,
            CardStatement.period_end == cutoff,
        )
    )
    if existing is not None:
        return existing
    spec = spec_for(card)
    period_start, period_end = cycles.cycle_for_cutoff(cutoff, spec)
    statement = CardStatement(
        space_id=card.space_id,
        credit_card_id=card.id,
        period_start=period_start,
        period_end=period_end,
        due_date=cycles.due_date_for(period_end, spec),
    )
    session.add(statement)
    await session.flush()
    return statement


async def assign_charge_to_statement(
    session: AsyncSession, card: CreditCard, txn: Transaction
) -> CardStatement:
    """TDC-05/TXN-06: assign a card charge to its billing cycle."""
    _, cutoff = cycles.cycle_for_purchase(txn.date, spec_for(card))
    statement = await get_or_create_statement(session, card, cutoff)
    txn.statement_id = statement.id
    return statement


async def get_statement(
    session: AsyncSession, space_id: uuid.UUID, statement_id: uuid.UUID
) -> CardStatement:
    statement = await session.get(CardStatement, statement_id)
    if statement is None or statement.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement no encontrado")
    return statement


async def _raw_statement_total(session: AsyncSession, statement: CardStatement) -> Decimal:
    """Charges − refunds + MSI installments charged into this statement.

    MSI-03: parent purchases (installment_plan_id != NULL) are excluded; their
    installments enter instead. Payments (transfers) live in paid_amount.
    """
    charges = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.statement_id == statement.id,
            Transaction.type == TransactionType.expense,
            Transaction.installment_plan_id.is_(None),
        )
    )
    refunds = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.statement_id == statement.id,
            Transaction.type == TransactionType.income,
        )
    )
    msi = await session.scalar(
        select(func.coalesce(func.sum(Installment.amount), 0)).where(
            Installment.statement_id == statement.id,
            Installment.status.in_([InstallmentStatus.charged, InstallmentStatus.paid]),
        )
    )
    return Decimal(charges or 0) - Decimal(refunds or 0) + Decimal(msi or 0)


async def recompute_statement_total(session: AsyncSession, statement_id: uuid.UUID) -> None:
    """Recompute a closed statement after charge edits/moves (TDC-06)."""
    statement = await session.get(CardStatement, statement_id)
    if statement is None or statement.status == StatementStatus.open:
        return
    statement.computed_total = (
        await _raw_statement_total(session, statement) - statement.applied_credit
    )
    _update_payment_status(statement)
    await session.flush()


def _update_payment_status(statement: CardStatement) -> None:
    """TDC-08 transitions for non-open statements."""
    if statement.status == StatementStatus.open:
        return
    if statement.paid_amount >= statement.computed_total:
        statement.status = StatementStatus.paid
    elif statement.paid_amount > ZERO:
        statement.status = StatementStatus.partially_paid
    else:
        statement.status = StatementStatus.closed


async def close_due_statements(
    session: AsyncSession, space: Space, today: date | None = None
) -> list[CardStatement]:
    """TDC-07: close every open statement with period_end < today. Closing:
    assigns due MSI installments (MSI-04/05), applies previous overpayment
    (TDC-10), computes the total and schedules reminders (REM-01).
    Idempotent: already-closed statements are skipped."""
    from app.services.reminders import schedule_card_reminders

    today = today or today_in_tz(space.timezone)
    closed: list[CardStatement] = []

    cards = (
        (await session.execute(select(CreditCard).where(CreditCard.space_id == space.id)))
        .scalars()
        .all()
    )
    for card in cards:
        spec = spec_for(card)
        # Materialize any statement whose cycle already ended (covers gaps
        # since the earliest charge thanks to on-demand creation TDC-11).
        while True:
            open_statements = (
                (
                    await session.execute(
                        select(CardStatement)
                        .where(
                            CardStatement.credit_card_id == card.id,
                            CardStatement.status == StatementStatus.open,
                            CardStatement.period_end < today,
                        )
                        .order_by(CardStatement.period_end)
                    )
                )
                .scalars()
                .all()
            )
            if not open_statements:
                break
            for statement in open_statements:
                # MSI-04/05: cuotas whose estimated date falls in this cycle.
                installments = (
                    (
                        await session.execute(
                            select(Installment)
                            .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
                            .where(
                                InstallmentPlan.credit_card_id == card.id,
                                Installment.status == InstallmentStatus.pending,
                                Installment.estimated_charge_date <= statement.period_end,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for installment in installments:
                    installment.statement_id = statement.id
                    installment.estimated_charge_date = statement.period_end
                    installment.status = InstallmentStatus.charged

                # TDC-10: previous overpayment becomes credit here.
                previous = await session.scalar(
                    select(CardStatement)
                    .where(
                        CardStatement.credit_card_id == card.id,
                        CardStatement.period_end < statement.period_end,
                        CardStatement.status != StatementStatus.open,
                    )
                    .order_by(CardStatement.period_end.desc())
                    .limit(1)
                )
                credit = ZERO
                if previous is not None:
                    credit = max(previous.paid_amount - previous.computed_total, ZERO)
                statement.applied_credit = credit
                statement.computed_total = await _raw_statement_total(session, statement) - credit
                statement.status = StatementStatus.closed
                _update_payment_status(statement)
                await schedule_card_reminders(session, card, statement)
                closed.append(statement)
            await session.flush()

        # Keep one open statement materialized for the current cycle.
        current_cutoff = cycles.cutoff_on_or_after(today, spec)
        await get_or_create_statement(session, card, current_cutoff)

    await session.commit()
    return closed


# --- Payments (TDC-10) ----------------------------------------------------------


async def register_payment(
    session: AsyncSession,
    space: Space,
    user_id: uuid.UUID,
    card: CreditCard,
    *,
    amount: Decimal,
    from_payment_method_id: uuid.UUID,
    payment_date: date,
    statement_id: uuid.UUID | None = None,
) -> Transaction:
    """TDC-10: a card payment is a transfer (TXN-02) into the card's method,
    assigned to a statement. Excess stays as credit for the next close."""
    from app.services.reminders import cancel_card_reminders
    from app.services.transactions import TransactionInput, create_transaction

    if card.payment_method_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "La tarjeta no tiene método vinculado")

    if statement_id is not None:
        statement = await get_statement(session, space.id, statement_id)
        if statement.credit_card_id != card.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement no encontrado")
    else:
        # Default: oldest unpaid closed statement; fallback to the open one.
        candidate = await session.scalar(
            select(CardStatement)
            .where(
                CardStatement.credit_card_id == card.id,
                CardStatement.status.in_([StatementStatus.closed, StatementStatus.partially_paid]),
            )
            .order_by(CardStatement.period_end)
            .limit(1)
        )
        if candidate is None:
            cutoff = cycles.cutoff_on_or_after(today_in_tz(space.timezone), spec_for(card))
            candidate = await get_or_create_statement(session, card, cutoff)
        statement = candidate

    txn = await create_transaction(
        session,
        space,
        user_id,
        TransactionInput(
            type=TransactionType.transfer,
            date=payment_date,
            amount=amount,
            currency=card.currency,
            description=f"Pago {card.alias}",
            payment_method_id=from_payment_method_id,
            payment_method_to_id=card.payment_method_id,
        ),
    )
    txn.statement_id = statement.id
    statement.paid_amount = statement.paid_amount + amount
    _update_payment_status(statement)
    if statement.status == StatementStatus.paid:
        # MSI-05: cuotas of a paid statement become paid.
        installments = (
            (
                await session.execute(
                    select(Installment).where(Installment.statement_id == statement.id)
                )
            )
            .scalars()
            .all()
        )
        for installment in installments:
            if installment.status == InstallmentStatus.charged:
                installment.status = InstallmentStatus.paid
        await _complete_plans_if_done(session, [i.plan_id for i in installments])
        await cancel_card_reminders(session, statement)  # REM-01
    await session.commit()
    await session.refresh(txn)
    return txn


async def _complete_plans_if_done(session: AsyncSession, plan_ids: list[uuid.UUID]) -> None:
    for plan_id in set(plan_ids):
        plan = await session.get(InstallmentPlan, plan_id)
        if plan is None or plan.status != PlanStatus.active:
            continue
        remaining = await session.scalar(
            select(func.count())
            .select_from(Installment)
            .where(
                Installment.plan_id == plan.id,
                Installment.status.in_([InstallmentStatus.pending, InstallmentStatus.charged]),
            )
        )
        if not remaining:
            plan.status = PlanStatus.completed


# --- Debt (TDC-09) ---------------------------------------------------------------


async def debt_summary(session: AsyncSession, card: CreditCard) -> dict[str, Decimal]:
    """TDC-09: (a) saldo al corte, (b) gasto del ciclo en curso,
    (c) comprometido futuro MSI. Deuda total = a + b + c."""
    closed_unpaid = (
        (
            await session.execute(
                select(CardStatement).where(
                    CardStatement.credit_card_id == card.id,
                    CardStatement.status.in_(
                        [StatementStatus.closed, StatementStatus.partially_paid]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    statement_balance = sum(
        (max(s.computed_total - s.paid_amount, ZERO) for s in closed_unpaid), ZERO
    )

    open_statements = (
        (
            await session.execute(
                select(CardStatement).where(
                    CardStatement.credit_card_id == card.id,
                    CardStatement.status == StatementStatus.open,
                )
            )
        )
        .scalars()
        .all()
    )
    current_cycle = ZERO
    for statement in open_statements:
        current_cycle += await _raw_statement_total(session, statement)

    pending_msi = await session.scalar(
        select(func.coalesce(func.sum(Installment.amount), 0))
        .select_from(Installment)
        .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
        .where(
            InstallmentPlan.credit_card_id == card.id,
            Installment.status == InstallmentStatus.pending,
        )
    )
    pending_msi = Decimal(pending_msi if pending_msi is not None else 0)

    return {
        "statement_balance": statement_balance,
        "current_cycle_spend": current_cycle,
        "committed_msi": pending_msi,
        "total_debt": statement_balance + current_cycle + pending_msi,
    }


# --- Reassignment (TDC-06) -------------------------------------------------------


async def move_charge_cycle(
    session: AsyncSession,
    space: Space,
    user_id: uuid.UUID,
    txn: Transaction,
    direction: str,
) -> Transaction:
    """TDC-06: move a charge one cycle back/forward; recompute both statements."""
    if txn.statement_id is None or txn.credit_card_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El cargo no tiene ciclo")
    if direction not in ("prev", "next"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "direction: prev | next")

    card = await get_card(session, space.id, txn.credit_card_id)
    spec = spec_for(card)
    current = await get_statement(session, space.id, txn.statement_id)
    if direction == "prev":
        target_cutoff = cycles.previous_cutoff(current.period_end, spec)
    else:
        target_cutoff = cycles.next_cutoff(current.period_end, spec)
    target = await get_or_create_statement(session, card, target_cutoff)

    old_id = txn.statement_id
    txn.statement_id = target.id
    txn.updated_by = user_id  # TDC-06: auditada
    await session.flush()
    await recompute_statement_total(session, old_id)
    await recompute_statement_total(session, target.id)
    await session.commit()
    await session.refresh(txn)
    return txn
