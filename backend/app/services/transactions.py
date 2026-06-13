"""Transaction services. Implements TXN-01..TXN-06, FX-03, REC-03 (discard).

GLO-01: Decimal everywhere. GLO-02: pure dates. GLO-05: space-scoped.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.catalogs import Category, CategoryKind, ExpenseNature, PaymentMethod
from app.models.recurring import RecurringTombstone
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import fx

# TXN-04: supported transaction currencies in v1 (crypto lives in INV).
SUPPORTED_CURRENCIES = {"MXN", "USD"}


@dataclass
class TransactionInput:
    type: TransactionType
    date: date
    amount: Decimal
    currency: str
    description: str = ""
    notes: str | None = None
    category_id: uuid.UUID | None = None
    payment_method_id: uuid.UUID | None = None
    payment_method_to_id: uuid.UUID | None = None
    expense_nature_override: ExpenseNature | None = None
    fx_rate_override: Decimal | None = None


async def _validate_category(
    session: AsyncSession,
    space_id: uuid.UUID,
    category_id: uuid.UUID,
    txn_type: TransactionType,
) -> Category:
    category = await session.get(Category, category_id)
    if category is None or category.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoría no encontrada")
    # TXN-01: category kind must match the transaction type.
    expected = CategoryKind.expense if txn_type == TransactionType.expense else CategoryKind.income
    if category.kind != expected:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "La categoría no corresponde al tipo de transacción",
        )
    if not category.is_active:
        # CAT-04: inactive categories are kept in history but not for capture.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Categoría inactiva")
    return category


async def _validate_payment_method(
    session: AsyncSession, space_id: uuid.UUID, method_id: uuid.UUID
) -> PaymentMethod:
    method = await session.get(PaymentMethod, method_id)
    if method is None or method.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Método de pago no encontrado")
    if not method.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Método de pago inactivo")
    return method


def _validate_date(txn_date: date, space: Space) -> None:
    # TXN-03: past/present always; future capped at +1 year.
    today = today_in_tz(space.timezone)
    if txn_date > today + relativedelta(years=1):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "La fecha no puede ser mayor a un año en el futuro",
        )


async def _resolve_fx_rate(
    session: AsyncSession,
    space: Space,
    currency: str,
    txn_date: date,
    override: Decimal | None,
) -> Decimal | None:
    """FX-03: freeze the rate of the transaction date (or closest previous);
    the user may override it manually. None when currency == base."""
    if currency == space.base_currency:
        return None
    if override is not None:
        return override
    rate = await fx.get_rate(session, currency, space.base_currency, txn_date)
    if rate is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Sin tipo de cambio disponible para {currency} al {txn_date.isoformat()}",
        )
    return rate


async def _validate_input(
    session: AsyncSession, space: Space, data: TransactionInput
) -> uuid.UUID | None:
    """Shared TXN-01/02 validation. Returns the credit card id derived from
    the payment method (TXN-06), if any."""
    if data.currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Moneda no soportada: {data.currency}",
        )
    _validate_date(data.date, space)

    credit_card_id: uuid.UUID | None = None
    if data.type == TransactionType.transfer:
        # TXN-02: transfer needs distinct from/to methods and no category.
        if not data.payment_method_id or not data.payment_method_to_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Una transferencia requiere método origen y destino",
            )
        if data.payment_method_id == data.payment_method_to_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Los métodos origen y destino deben ser distintos",
            )
        if data.category_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Una transferencia no lleva categoría",
            )
        await _validate_payment_method(session, space.id, data.payment_method_id)
        await _validate_payment_method(session, space.id, data.payment_method_to_id)
    else:
        # TXN-01: expense/income require category + payment method.
        if data.category_id is None or data.payment_method_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Categoría y método de pago son obligatorios",
            )
        await _validate_category(session, space.id, data.category_id, data.type)
        method = await _validate_payment_method(session, space.id, data.payment_method_id)
        # TXN-06: charges on a credit-card method belong to a billing cycle.
        credit_card_id = method.credit_card_id
        if data.payment_method_to_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Solo las transferencias llevan método destino",
            )
    return credit_card_id


async def get_transaction(
    session: AsyncSession, space_id: uuid.UUID, txn_id: uuid.UUID
) -> Transaction:
    txn = await session.get(Transaction, txn_id)
    if txn is None or txn.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transacción no encontrada")
    return txn


async def create_transaction(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    data: TransactionInput,
    *,
    recurring_rule_id: uuid.UUID | None = None,
    scheduled_date: date | None = None,
    needs_review: bool = False,
) -> Transaction:
    credit_card_id = await _validate_input(session, space, data)
    fx_rate = await _resolve_fx_rate(
        session, space, data.currency, data.date, data.fx_rate_override
    )
    txn = Transaction(
        space_id=space.id,
        type=data.type,
        date=data.date,
        description=data.description,
        notes=data.notes,
        amount=data.amount,
        currency=data.currency,
        fx_rate_to_base=fx_rate,
        category_id=data.category_id,
        expense_nature_override=data.expense_nature_override,
        payment_method_id=data.payment_method_id,
        payment_method_to_id=data.payment_method_to_id,
        credit_card_id=credit_card_id,
        recurring_rule_id=recurring_rule_id,
        scheduled_date=scheduled_date,
        needs_review=needs_review,
        created_by=created_by,
    )
    session.add(txn)
    await session.flush()
    if credit_card_id is not None and data.type != TransactionType.transfer:
        # TXN-06/TDC-05: card charges belong to a billing cycle.
        from app.services.cards import assign_charge_to_statement, get_card

        card = await get_card(session, space.id, credit_card_id)
        await assign_charge_to_statement(session, card, txn)
    await session.commit()
    await session.refresh(txn)
    return txn


async def update_transaction(
    session: AsyncSession,
    space: Space,
    updated_by: uuid.UUID,
    txn_id: uuid.UUID,
    data: TransactionInput,
) -> Transaction:
    """TXN-05: editing keeps recurring/import provenance for traceability.
    FX-03 (mandatory case 6): the frozen rate only changes if the date or the
    currency change (or with an explicit manual override)."""
    txn = await get_transaction(session, space.id, txn_id)
    # MSI-08: a purchase that originated an installment plan is managed through
    # the plan UI (adjust cuota by cuota); block direct editing here.
    if txn.installment_plan_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Esta transacción tiene un plan MSI activo; ajusta las cuotas desde el plan",
        )
    credit_card_id = await _validate_input(session, space, data)

    if data.fx_rate_override is not None:
        txn.fx_rate_to_base = data.fx_rate_override
    elif data.currency != txn.currency or data.date != txn.date:
        txn.fx_rate_to_base = await _resolve_fx_rate(session, space, data.currency, data.date, None)
    # else: keep the frozen rate untouched (FX-03).

    txn.type = data.type
    txn.date = data.date
    txn.description = data.description
    txn.notes = data.notes
    txn.amount = data.amount
    txn.currency = data.currency
    txn.category_id = data.category_id
    txn.expense_nature_override = data.expense_nature_override
    txn.payment_method_id = data.payment_method_id
    txn.payment_method_to_id = data.payment_method_to_id
    txn.credit_card_id = credit_card_id
    txn.updated_by = updated_by
    txn.needs_review = False  # REC-03: adjusting counts as reviewing.

    # TDC-05: re-resolve the cycle (date or method may have changed) and
    # recompute any closed statement totals affected.
    from app.services.cards import assign_charge_to_statement, get_card, recompute_statement_total

    old_statement_id = txn.statement_id
    if credit_card_id is not None and data.type != TransactionType.transfer:
        card = await get_card(session, space.id, credit_card_id)
        await assign_charge_to_statement(session, card, txn)
    elif txn.statement_id is not None and data.type != TransactionType.transfer:
        txn.statement_id = None
    await session.flush()
    if old_statement_id is not None and old_statement_id != txn.statement_id:
        await recompute_statement_total(session, old_statement_id)
    if txn.statement_id is not None:
        await recompute_statement_total(session, txn.statement_id)

    await session.commit()
    await session.refresh(txn)
    return txn


async def delete_transaction(session: AsyncSession, space_id: uuid.UUID, txn_id: uuid.UUID) -> None:
    txn = await get_transaction(session, space_id, txn_id)
    if txn.installment_plan_id is not None:
        # MSI-08: deleting the purchase deletes the plan only if every
        # installment is still pending; otherwise it's blocked.
        from sqlalchemy.orm import selectinload

        from app.models.msi import InstallmentPlan
        from app.services.msi import delete_plan_if_allowed

        plan = await session.get(
            InstallmentPlan,
            txn.installment_plan_id,
            options=[selectinload(InstallmentPlan.installments)],
        )
        if plan is not None:
            await delete_plan_if_allowed(session, plan)
    old_statement_id = txn.statement_id
    if txn.recurring_rule_id is not None and txn.scheduled_date is not None:
        # REC-03: discarding a generated instance leaves a tombstone so the
        # job never regenerates it.
        existing = await session.scalar(
            select(RecurringTombstone.id).where(
                RecurringTombstone.rule_id == txn.recurring_rule_id,
                RecurringTombstone.scheduled_date == txn.scheduled_date,
            )
        )
        if existing is None:
            session.add(
                RecurringTombstone(rule_id=txn.recurring_rule_id, scheduled_date=txn.scheduled_date)
            )
    await session.delete(txn)
    await session.flush()
    if old_statement_id is not None:
        from app.services.cards import recompute_statement_total

        await recompute_statement_total(session, old_statement_id)
    await session.commit()


async def confirm_transaction(
    session: AsyncSession,
    space_id: uuid.UUID,
    txn_id: uuid.UUID,
    amount: Decimal | None = None,
) -> Transaction:
    """REC-03: one-tap confirm from the review tray, optionally adjusting the
    amount (variable bills)."""
    txn = await get_transaction(session, space_id, txn_id)
    if amount is not None:
        if amount <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Monto inválido")
        txn.amount = amount
    txn.needs_review = False
    await session.commit()
    await session.refresh(txn)
    return txn
