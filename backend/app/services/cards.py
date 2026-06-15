"""Credit cards and statements. Implements TDC-01..TDC-12, MSI-05, REM-01.

The pure cycle math lives in services/billing_cycles.py; this module owns
persistence: cards, statement materialization (TDC-11), charge assignment
(TDC-05/TXN-06), closing (TDC-07), payments (TDC-10) and debt (TDC-09).
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.core.text import normalize_name
from app.models.cards import Card, CardStatement, StatementStatus
from app.models.catalogs import (
    CardBehavior,
    CardType,
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


def spec_for(card: Card) -> cycles.CardCycleSpec:
    return cycles.CardCycleSpec(
        statement_day="last" if card.statement_day_is_last else (card.statement_day or 1),
        # str() works whether the attribute holds the StrEnum member or a raw
        # string not yet round-tripped through the DB (e.g. just-built card).
        cutoff_day_policy=str(card.cutoff_day_policy),
        payment_due_days=card.payment_due_days,
        payment_day="last"
        if card.payment_day_is_last
        else card.payment_day
        if card.payment_day is not None
        else None,
    )


async def get_card(session: AsyncSession, space_id: uuid.UUID, card_id: uuid.UUID) -> Card:
    card = await session.get(Card, card_id)
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


_METHOD_TYPE_FOR: dict[CardBehavior, PaymentMethodType] = {
    CardBehavior.credit: PaymentMethodType.credit_card,
    CardBehavior.debit: PaymentMethodType.debit,
    CardBehavior.prepaid: PaymentMethodType.prepaid,
}


def cycle_ready(card: Card) -> bool:
    """TDC-15: a credit card runs its cycle engine only once it has a cut day.
    Until then its charges are not assigned to any statement."""
    return card.statement_day is not None or card.statement_day_is_last


def _payment_ready(card: Card) -> bool:
    """A card has its payment terms set (needed to compute a due_date)."""
    return (
        card.payment_due_days is not None
        or card.payment_day is not None
        or card.payment_day_is_last
    )


def _resolve_credit_fields(
    statement_day: int | str | None,
    payment_due_days: int | None,
    payment_day: int | str | None,
) -> dict[str, object]:
    """TDC-01/TDC-15: validate the (optional) cycle config. Fields may be left
    unset for a partially-captured card; at most one payment rule is allowed."""
    if payment_due_days is not None and payment_day is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Define a lo más uno: payment_due_days o payment_day",
        )
    if payment_due_days is not None and not 1 <= payment_due_days <= 30:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "payment_due_days fuera de 1-30")
    try:
        if statement_day is not None:
            cycles.statement_cutoff(statement_day, 2026, 1)
        if payment_day is not None:
            cycles.statement_cutoff(payment_day, 2026, 1)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    stmt_is_last = statement_day == "last"
    pay_is_last = payment_day == "last"
    return {
        "statement_day": None if (statement_day is None or stmt_is_last) else int(statement_day),
        "statement_day_is_last": stmt_is_last,
        "payment_due_days": payment_due_days,
        "payment_day": int(payment_day) if (payment_day is not None and not pay_is_last) else None,
        "payment_day_is_last": pay_is_last,
    }


async def _statement_has_charges(session: AsyncSession, statement_id: uuid.UUID) -> bool:
    """Whether any transaction or MSI installment is assigned to a statement."""
    txn = await session.scalar(
        select(Transaction.id).where(Transaction.statement_id == statement_id).limit(1)
    )
    if txn is not None:
        return True
    inst = await session.scalar(
        select(Installment.id).where(Installment.statement_id == statement_id).limit(1)
    )
    return inst is not None


async def get_opening_balance(
    session: AsyncSession, space: Space, card: Card
) -> Decimal | None:
    """TDC-14: return the computed_total of the synthetic opening-balance statement
    (previous period, no itemized charges), or None if no such statement exists."""
    if not (cycle_ready(card) and _payment_ready(card)):
        return None
    spec = spec_for(card)
    today = today_in_tz(space.timezone)
    opening_cutoff = cycles.previous_cutoff(cycles.cutoff_on_or_after(today, spec), spec)
    _, period_end = cycles.cycle_for_cutoff(opening_cutoff, spec)
    existing = await session.scalar(
        select(CardStatement).where(
            CardStatement.credit_card_id == card.id,
            CardStatement.period_end == period_end,
        )
    )
    if existing is None:
        return None
    if await _statement_has_charges(session, existing.id):
        return None
    return existing.computed_total


async def set_opening_balance(
    session: AsyncSession, space: Space, card: Card, amount: Decimal
) -> CardStatement | None:
    """TDC-14: record the pending debt from the previous cut as a closed
    statement (due at the next payment date) so it enters TDC-09 (saldo al
    corte) and is paid via TDC-10. Create-or-update on the previous cut; never
    overwrite a cut that already has itemized charges. Usable at alta and edit."""
    if not (cycle_ready(card) and _payment_ready(card)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Para registrar deuda inicial configura el día de corte y los términos de pago",
        )
    spec = spec_for(card)
    today = today_in_tz(space.timezone)
    opening_cutoff = cycles.previous_cutoff(cycles.cutoff_on_or_after(today, spec), spec)
    period_start, period_end = cycles.cycle_for_cutoff(opening_cutoff, spec)

    existing = await session.scalar(
        select(CardStatement).where(
            CardStatement.credit_card_id == card.id,
            CardStatement.period_end == period_end,
        )
    )
    if existing is None and amount == ZERO:
        return None  # Nothing to zero out; skip creating a zero-balance statement.
    if existing is not None:
        if await _statement_has_charges(session, existing.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ya hay cargos en el corte anterior; no se puede sobreponer un saldo manual",
            )
        existing.computed_total = amount
        existing.status = StatementStatus.closed
        _update_payment_status(existing)
        await session.flush()
        return existing

    statement = CardStatement(
        space_id=space.id,
        credit_card_id=card.id,
        period_start=period_start,
        period_end=period_end,
        due_date=cycles.due_date_for(period_end, spec),
        computed_total=amount,
        paid_amount=ZERO,
        status=StatementStatus.closed,
    )
    session.add(statement)
    await session.flush()
    return statement


async def next_payment_due(session: AsyncSession, card: Card) -> tuple[Decimal, date] | None:
    """TDC-09/TDC-14: the nearest closed (unpaid) statement to settle — the
    amount due at the upcoming payment date."""
    statements = (
        (
            await session.execute(
                select(CardStatement)
                .where(
                    CardStatement.credit_card_id == card.id,
                    CardStatement.status.in_(
                        [StatementStatus.closed, StatementStatus.partially_paid]
                    ),
                )
                .order_by(CardStatement.due_date)
            )
        )
        .scalars()
        .all()
    )
    for statement in statements:
        outstanding = statement.computed_total - statement.paid_amount
        if outstanding > ZERO:
            return outstanding, statement.due_date
    return None


async def create_card(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    card_type_id: uuid.UUID,
    alias: str,
    bank: str,
    network: str,
    last4: str,
    currency: str = "MXN",
    # TAR-02 credit-only fields (all optional, TDC-15: may be filled later).
    statement_day: int | str | None = None,
    cutoff_day_policy: str = "include",
    payment_due_days: int | None = None,
    payment_day: int | str | None = None,
    credit_limit: Decimal | None = None,
    reminder_days: list[int] | None = None,
    opening_balance: Decimal | None = None,  # TDC-14: deuda del corte anterior
    # TAR-05 non-credit fields.
    initial_balance: Decimal | None = None,
    allow_overdraft: bool = False,
    color: str | None = None,
) -> Card:
    """TAR-01/03 + TDC-01 + CAT-07: creates the card and its linked method.
    Credit cards carry (optional) cycle fields and an optional opening debt
    (TDC-14); debit/prepaid carry a balance."""
    from app.services.catalogs import get_card_type

    if not (last4.isdigit() and len(last4) == 4):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "last4 debe ser 4 dígitos")

    card_type = await get_card_type(session, space.id, card_type_id)  # GLO-05: 404 cross-space
    behavior = card_type.behavior

    if behavior == CardBehavior.credit:
        # TDC-15: cycle fields are optional and can be completed later via edit.
        if initial_balance is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Una tarjeta de crédito no lleva saldo inicial",
            )
        cfg = _resolve_credit_fields(statement_day, payment_due_days, payment_day)
        card = Card(
            space_id=space.id,
            card_type_id=card_type_id,
            alias=alias,
            bank=bank,
            network=network,
            last4=last4,
            currency=currency,
            credit_limit=credit_limit,
            cutoff_day_policy=cutoff_day_policy,
            reminder_days=reminder_days if reminder_days is not None else [3, 1],
            color=color,
            created_by=created_by,
            **cfg,
        )
    else:
        # TAR-02: non-credit must not carry credit fields; it carries a balance.
        if any(
            v is not None
            for v in (statement_day, payment_due_days, payment_day, credit_limit, opening_balance)
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Una tarjeta no-crédito no lleva campos de corte/pago/límite/deuda",
            )
        card = Card(
            space_id=space.id,
            card_type_id=card_type_id,
            alias=alias,
            bank=bank,
            network=network,
            last4=last4,
            currency=currency,
            initial_balance=initial_balance if initial_balance is not None else ZERO,
            allow_overdraft=allow_overdraft,
            reminder_days=[],
            color=color,
            created_by=created_by,
        )
    session.add(card)
    await session.flush()

    # CAT-07/TAR-03: auto-create the linked payment method, type per behavior.
    method = PaymentMethod(
        space_id=space.id,
        name=alias,
        name_normalized=normalize_name(alias),
        type=_METHOD_TYPE_FOR[behavior],
        card_id=card.id,
        created_by=created_by,
    )
    session.add(method)
    await session.flush()
    card.payment_method_id = method.id
    if behavior == CardBehavior.credit:
        await _ensure_fees_category(session, space.id, created_by)  # TDC-13
        if opening_balance is not None and opening_balance > ZERO:
            await set_opening_balance(session, space, card, opening_balance)  # TDC-14
    await session.commit()
    await session.refresh(card)
    return card


async def update_card(
    session: AsyncSession, space: Space, card: Card, changes: dict[str, object]
) -> Card:
    """TDC-15: full edit of a card (like a transaction edit). Re-validates the
    fields present in `changes`, behavior-aware. Card type/behavior is fixed."""
    behavior = await card_behavior(session, card)
    credit_only = {
        "statement_day",
        "cutoff_day_policy",
        "payment_due_days",
        "payment_day",
        "credit_limit",
        "reminder_days",
    }
    balance_only = {"initial_balance", "allow_overdraft"}
    if behavior != CardBehavior.credit and credit_only & changes.keys():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Esta tarjeta no lleva campos de corte/pago/límite",
        )
    if behavior == CardBehavior.credit and balance_only & changes.keys():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Una tarjeta de crédito no lleva saldo"
        )
    if "last4" in changes:
        last4 = changes["last4"]
        if not (isinstance(last4, str) and last4.isdigit() and len(last4) == 4):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "last4 debe ser 4 dígitos")

    # Re-derive the cycle config if any cut/payment field changed (TDC-15).
    if (
        behavior == CardBehavior.credit
        and {
            "statement_day",
            "payment_due_days",
            "payment_day",
        }
        & changes.keys()
    ):
        cur_sd: int | str | None = "last" if card.statement_day_is_last else card.statement_day
        cur_pd: int | str | None = "last" if card.payment_day_is_last else card.payment_day
        eff_sd = changes["statement_day"] if "statement_day" in changes else cur_sd
        eff_pdd = (
            changes["payment_due_days"] if "payment_due_days" in changes else card.payment_due_days
        )
        eff_pd = changes["payment_day"] if "payment_day" in changes else cur_pd
        for key, value in _resolve_credit_fields(eff_sd, eff_pdd, eff_pd).items():  # type: ignore[arg-type]
            setattr(card, key, value)

    for field in (
        "alias",
        "bank",
        "network",
        "last4",
        "currency",
        "color",
        "cutoff_day_policy",
        "credit_limit",
        "reminder_days",
        "initial_balance",
        "allow_overdraft",
    ):
        if field in changes:
            setattr(card, field, changes[field])

    # Keep the linked payment method name in sync with the alias (CAT-07).
    if "alias" in changes and card.payment_method_id is not None:
        method = await session.get(PaymentMethod, card.payment_method_id)
        if method is not None:
            normalized = normalize_name(str(changes["alias"]))
            dup = await session.scalar(
                select(PaymentMethod.id).where(
                    PaymentMethod.space_id == space.id,
                    PaymentMethod.name_normalized == normalized,
                    PaymentMethod.id != method.id,
                )
            )
            if dup is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "Ya existe un método de pago con ese nombre"
                )
            method.name = str(changes["alias"])
            method.name_normalized = normalized

    # TDC-14: pending balance from the previous cut (credit only). Applied last
    # so it reads any cut/payment fields updated in this same edit.
    if "opening_balance" in changes:
        if behavior != CardBehavior.credit:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Solo las tarjetas de crédito llevan deuda del corte anterior",
            )
        amount = changes["opening_balance"]
        if isinstance(amount, Decimal) and amount >= ZERO:
            await set_opening_balance(session, space, card, amount)

    await session.commit()
    await session.refresh(card)
    return card


async def set_card_active(session: AsyncSession, card: Card, active: bool) -> None:
    """Reactivate a card and its linked method (mirror of deactivate_card)."""
    card.is_active = active
    if card.payment_method_id is not None:
        method = await session.get(PaymentMethod, card.payment_method_id)
        if method is not None:
            method.is_active = active  # CAT-07
    await session.commit()


async def card_behavior(session: AsyncSession, card: Card) -> CardBehavior:
    """TAR-01: the card's behavior, read from its type (CAT-08)."""
    card_type = await session.get(CardType, card.card_type_id)
    assert card_type is not None
    return card_type.behavior


async def card_balance(
    session: AsyncSession, card: Card, exclude_txn_id: uuid.UUID | None = None
) -> Decimal:
    """TAR-05: stored-value balance for debit/prepaid, computed in SQL:
    initial + income + incoming transfers − expenses − outgoing transfers,
    over the card's linked payment method. `exclude_txn_id` ignores one
    transaction (used while validating an edit)."""
    if card.payment_method_id is None:
        return ZERO
    method_id = card.payment_method_id
    scope: list[ColumnElement[bool]] = [Transaction.space_id == card.space_id]
    if exclude_txn_id is not None:
        scope.append(Transaction.id != exclude_txn_id)

    async def total(*predicates: ColumnElement[bool]) -> Decimal:
        value = await session.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(*scope, *predicates)
        )
        return Decimal(value or 0)

    inflow_income = await total(
        Transaction.type == TransactionType.income,
        Transaction.payment_method_id == method_id,
    )
    inflow_transfer = await total(
        Transaction.type == TransactionType.transfer,
        Transaction.payment_method_to_id == method_id,
    )
    outflow_expense = await total(
        Transaction.type == TransactionType.expense,
        Transaction.payment_method_id == method_id,
        Transaction.installment_plan_id.is_(None),  # MSI parent excluded
    )
    outflow_transfer = await total(
        Transaction.type == TransactionType.transfer,
        Transaction.payment_method_id == method_id,
    )
    initial = Decimal(card.initial_balance if card.initial_balance is not None else 0)
    return initial + inflow_income + inflow_transfer - outflow_expense - outflow_transfer


async def deactivate_card(session: AsyncSession, card: Card) -> None:
    """TDC-12: no new charges, but cycles keep closing until settled."""
    card.is_active = False
    if card.payment_method_id is not None:
        method = await session.get(PaymentMethod, card.payment_method_id)
        if method is not None:
            method.is_active = False  # CAT-07
    await session.commit()


# --- Statements ----------------------------------------------------------------


async def get_or_create_statement(session: AsyncSession, card: Card, cutoff: date) -> CardStatement:
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
    session: AsyncSession,
    card: Card,
    txn: Transaction,
    cycle_hint: str | None = None,
) -> CardStatement:
    """TDC-05/TXN-06: assign a card charge to its billing cycle.

    TDC-05a: if cycle_hint ('current'|'next') is provided and the transaction
    date falls exactly on the cutoff day, it overrides cutoff_day_policy.
    """
    spec = spec_for(card)
    if cycle_hint is not None:
        override = "include" if cycle_hint == "current" else "next_cycle"
        spec = cycles.CardCycleSpec(
            statement_day=spec.statement_day,
            cutoff_day_policy=override,
            payment_due_days=spec.payment_due_days,
            payment_day=spec.payment_day,
        )
    _, cutoff = cycles.cycle_for_purchase(txn.date, spec)
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

    # TAR-04: only credit cards have statements/cycles; skip debit/prepaid.
    # TDC-15: skip credit cards without a cut day configured yet.
    cards = (
        (
            await session.execute(
                select(Card)
                .join(CardType, Card.card_type_id == CardType.id)
                .where(
                    Card.space_id == space.id,
                    CardType.behavior == CardBehavior.credit,
                    Card.statement_day.is_not(None) | Card.statement_day_is_last.is_(True),
                )
            )
        )
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
    card: Card,
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
    # TDC-15: a statement target requires a configured cut day.
    if statement_id is None and not cycle_ready(card):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Configura el día de corte de la tarjeta antes de registrar pagos",
        )

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


async def debt_summary(session: AsyncSession, card: Card) -> dict[str, Decimal]:
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
    if txn.statement_id is None or txn.card_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El cargo no tiene ciclo")
    if direction not in ("prev", "next"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "direction: prev | next")

    card = await get_card(session, space.id, txn.card_id)
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
