"""Transaction services. Implements TXN-01..TXN-14, TAR-03/05/10, FX-03,
REC-03 (discard).

GLO-01: Decimal everywhere. GLO-02: pure dates. GLO-05: space-scoped.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.accounts import Account, Statement, StatementStatus
from app.models.catalogs import (
    BALANCE_BEHAVIORS,
    AccountBehavior,
    Category,
    CategoryKind,
    ExpenseNature,
)
from app.models.recurring import RecurringTombstone
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import fx

# TXN-04: supported transaction currencies in v1 (crypto lives in INV).
SUPPORTED_CURRENCIES = {"MXN", "USD"}
ZERO = Decimal("0.00")


@dataclass
class TransactionInput:
    type: TransactionType
    date: date
    amount: Decimal
    currency: str
    account_id: uuid.UUID  # TAR-03
    description: str = ""
    notes: str | None = None
    category_id: uuid.UUID | None = None
    account_to_id: uuid.UUID | None = None  # TXN-02
    amount_to: Decimal | None = None  # TXN-13
    fee_amount: Decimal | None = None  # TXN-14
    expense_nature_override: ExpenseNature | None = None
    fx_rate_override: Decimal | None = None
    cycle_hint: str | None = None  # TDC-05a: "current" | "next" | None
    target_statement_id: uuid.UUID | None = None  # TXN-09: explicit statement for TDC payment


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


async def validate_account(
    session: AsyncSession, space_id: uuid.UUID, account_id: uuid.UUID
) -> Account:
    """TAR-03/CAT-04: the account must belong to the space and be active."""
    account = await session.get(Account, account_id)
    if account is None or account.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    if not account.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cuenta inactiva")
    return account


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


@dataclass
class _Resolved:
    """The accounts behind a transaction and their behaviors (TAR-01)."""

    account: Account
    behavior: AccountBehavior
    target: Account | None = None
    target_behavior: AccountBehavior | None = None


def _reject(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


async def _validate_input(session: AsyncSession, space: Space, data: TransactionInput) -> _Resolved:
    """Shared TXN-01/02/13/14 + TAR-10 validation; resolves the accounts."""
    from app.services.accounts import account_behavior

    if data.currency not in SUPPORTED_CURRENCIES:
        raise _reject(f"Moneda no soportada: {data.currency}")
    _validate_date(data.date, space)

    account = await validate_account(session, space.id, data.account_id)
    # TAR-10: every movement goes in its account's currency.
    if data.currency != account.currency:
        raise _reject(
            f"La cuenta {account.name} maneja {account.currency}; "
            f"registra el monto en {account.currency}"
        )
    resolved = _Resolved(account=account, behavior=await account_behavior(session, account))

    if data.type == TransactionType.transfer:
        # TXN-02: transfer needs distinct source/target accounts and no category.
        if data.account_to_id is None:
            raise _reject("Una transferencia requiere cuenta origen y destino")
        if data.account_to_id == data.account_id:
            raise _reject("Las cuentas origen y destino deben ser distintas")
        if data.category_id is not None:
            raise _reject("Una transferencia no lleva categoría")
        target = await validate_account(session, space.id, data.account_to_id)
        # TXN-13: a cross-currency transfer states what the target receives.
        if target.currency != account.currency and data.amount_to is None:
            raise _reject(f"La cuenta destino maneja {target.currency}: indica el monto que recibe")
        if target.currency == account.currency and data.amount_to is not None:
            raise _reject("El monto recibido solo aplica entre cuentas de distinta moneda")
        resolved.target = target
        resolved.target_behavior = await account_behavior(session, target)
        return resolved

    # TXN-01: expense/income require a category; TXN-13/14 are transfer-only.
    if data.category_id is None:
        raise _reject("La categoría es obligatoria")
    await _validate_category(session, space.id, data.category_id, data.type)
    if data.account_to_id is not None:
        raise _reject("Solo las transferencias llevan cuenta destino")
    if data.amount_to is not None or data.fee_amount is not None:
        raise _reject("El monto recibido y la comisión solo aplican a transferencias")
    return resolved


async def _check_sufficient_funds(
    session: AsyncSession,
    resolved: _Resolved,
    data: TransactionInput,
    exclude_txn_ids: tuple[uuid.UUID, ...] = (),
) -> None:
    """TAR-05/TXN-08: a balance account cannot be overdrawn by an expense or an
    outgoing transfer (plus its fee, TXN-14) unless it allows it (cash always
    does, TAR-09)."""
    if data.type == TransactionType.income:
        return
    if resolved.behavior not in BALANCE_BEHAVIORS or resolved.account.allow_overdraft:
        return

    from app.services.accounts import account_balance

    needed = data.amount + (data.fee_amount or ZERO)
    available = await account_balance(session, resolved.account, exclude_txn_ids=exclude_txn_ids)
    if needed > available:
        raise _reject(f"Saldo insuficiente en {resolved.account.name} (disponible {available})")


def like_pattern(text: str) -> str:
    """TXN-12: substring ILIKE pattern with `%`, `_` and `\\` escaped as literals."""
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def find_possible_duplicates(
    session: AsyncSession,
    space_id: uuid.UUID,
    txn_type: TransactionType,
    txn_date: date,
    amount: Decimal,
    currency: str,
    description: str,
    category_id: uuid.UUID | None,
) -> list[Transaction]:
    """TXN-11: same type, date, amount, currency, category and normalized
    description. The account is ignored on purpose (same expense captured as
    cash and then again with a card)."""
    rows = await session.execute(
        select(Transaction)
        .where(
            Transaction.space_id == space_id,
            Transaction.type == txn_type,
            Transaction.date == txn_date,
            Transaction.amount == amount,
            Transaction.currency == currency,
            Transaction.category_id.is_not_distinct_from(category_id),
            func.lower(func.trim(Transaction.description)) == description.strip().lower(),
        )
        .order_by(Transaction.created_at.desc())
        .limit(10)
    )
    return list(rows.scalars().all())


async def get_fee(session: AsyncSession, transfer_id: uuid.UUID) -> Transaction | None:
    """TXN-14: the fee row attached to a transfer, if any."""
    fee: Transaction | None = await session.scalar(
        select(Transaction).where(Transaction.fee_for_id == transfer_id)
    )
    return fee


async def fee_amounts(
    session: AsyncSession, txns: Sequence[Transaction]
) -> dict[uuid.UUID, Decimal]:
    """TXN-14: {transfer id: fee amount} for the transfers in `txns` (one query)."""
    ids = [t.id for t in txns if t.type == TransactionType.transfer]
    if not ids:
        return {}
    rows = await session.execute(
        select(Transaction.fee_for_id, Transaction.amount).where(Transaction.fee_for_id.in_(ids))
    )
    return {fee_for_id: amount for fee_for_id, amount in rows.all() if fee_for_id is not None}


async def get_transaction(
    session: AsyncSession, space_id: uuid.UUID, txn_id: uuid.UUID
) -> Transaction:
    txn = await session.get(Transaction, txn_id)
    if txn is None or txn.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transacción no encontrada")
    return txn


async def _assign_credit_charge(
    session: AsyncSession, resolved: _Resolved, txn: Transaction, cycle_hint: str | None
) -> uuid.UUID | None:
    """TXN-06/TDC-05: a credit charge (or refund, TDC-16) joins its billing
    cycle. Returns the statement id, or None when the account isn't a
    cycle-ready credit card (TDC-15) or the movement is a transfer."""
    from app.services.accounts import (
        assign_charge_to_statement,
        assign_refund_to_statement,
        cycle_ready,
    )

    if (
        resolved.behavior != AccountBehavior.credit
        or not cycle_ready(resolved.account)
        or txn.type == TransactionType.transfer
    ):
        return None
    if txn.type == TransactionType.income:
        stmt = await assign_refund_to_statement(session, resolved.account, txn)
    else:
        stmt = await assign_charge_to_statement(
            session, resolved.account, txn, cycle_hint=cycle_hint
        )
    return stmt.id


async def _create_fee(
    session: AsyncSession,
    space: Space,
    user_id: uuid.UUID,
    transfer: Transaction,
    resolved: _Resolved,
    fee_amount: Decimal,
) -> None:
    """TXN-14: the transfer's fee is an expense of the source account, in its
    currency, under 'Comisiones e intereses'. It counts as spending (DSH-02)."""
    from app.services.accounts import ensure_fees_category, recompute_statement_total

    category = await ensure_fees_category(session, space.id, user_id)
    fee = Transaction(
        space_id=space.id,
        type=TransactionType.expense,
        date=transfer.date,
        description=f"Comisión: {transfer.description or 'transferencia'}"[:200],
        amount=fee_amount,
        currency=transfer.currency,
        fx_rate_to_base=transfer.fx_rate_to_base,
        category_id=category.id,
        account_id=transfer.account_id,
        fee_for_id=transfer.id,
        created_by=user_id,
    )
    session.add(fee)
    await session.flush()
    statement_id = await _assign_credit_charge(session, resolved, fee, None)
    if statement_id is not None:
        await session.flush()
        await recompute_statement_total(session, statement_id)


async def _drop_fee(session: AsyncSession, transfer: Transaction) -> None:
    """TXN-14: remove a transfer's fee (on edit or delete), keeping the
    statement it was charged to (credit source) consistent."""
    from app.services.accounts import recompute_statement_total

    fee = await get_fee(session, transfer.id)
    if fee is None:
        return
    statement_id = fee.statement_id
    await session.delete(fee)
    await session.flush()
    if statement_id is not None:
        await recompute_statement_total(session, statement_id)


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
    from app.services.accounts import apply_card_payment, recompute_statement_total

    resolved = await _validate_input(session, space, data)
    await _check_sufficient_funds(session, resolved, data)  # TAR-05
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
        account_id=data.account_id,
        account_to_id=data.account_to_id,
        amount_to=data.amount_to,
        recurring_rule_id=recurring_rule_id,
        scheduled_date=scheduled_date,
        needs_review=needs_review,
        created_by=created_by,
    )
    session.add(txn)
    await session.flush()

    statement_id = await _assign_credit_charge(session, resolved, txn, data.cycle_hint)
    if statement_id is not None:
        # TDC-06: a late charge on an already-closed cycle recomputes its total.
        statement = await session.get(Statement, statement_id)
        if statement is not None and statement.status != StatementStatus.open:
            await recompute_statement_total(session, statement_id)
    if resolved.target is not None and resolved.target_behavior == AccountBehavior.credit:
        # TXN-09: a transfer into a credit account is a TDC payment.
        await apply_card_payment(session, space, resolved.target, txn, data.target_statement_id)
    if data.type == TransactionType.transfer and data.fee_amount is not None:
        await _create_fee(session, space, created_by, txn, resolved, data.fee_amount)
    await session.commit()
    await session.refresh(txn)
    return txn


def _reject_fee_row(txn: Transaction) -> None:
    """TXN-14: a fee row is managed only through its transfer."""
    if txn.fee_for_id is not None:
        raise _reject("Esta comisión se edita o elimina desde su transferencia")


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
    from app.services.accounts import (
        apply_card_payment,
        received_amount,
        recompute_statement_total,
        revert_card_payment,
    )

    txn = await get_transaction(session, space.id, txn_id)
    _reject_fee_row(txn)
    # MSI-08: a purchase that originated an installment plan is managed through
    # the plan UI (adjust cuota by cuota); block direct editing here.
    if txn.installment_plan_id is not None:
        raise _reject("Esta transacción tiene un plan MSI activo; ajusta las cuotas desde el plan")
    resolved = await _validate_input(session, space, data)
    # TAR-05: the edited amount cannot overdraw the balance (excluding itself
    # and its current fee, which the edit replaces).
    current_fee = await get_fee(session, txn.id)
    excluded = (txn.id,) if current_fee is None else (txn.id, current_fee.id)
    await _check_sufficient_funds(session, resolved, data, exclude_txn_ids=excluded)

    # Pre-update state for the TXN-09 revert: what was actually applied.
    old_statement_id = txn.statement_id
    old_account_to_id = txn.account_to_id
    old_applied = received_amount(txn)
    was_tdc_payment = txn.type == TransactionType.transfer and old_statement_id is not None

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
    txn.account_id = data.account_id
    txn.account_to_id = data.account_to_id
    txn.amount_to = data.amount_to
    txn.updated_by = updated_by
    txn.needs_review = False  # REC-03: adjusting counts as reviewing.

    if was_tdc_payment:
        # TXN-09: undo the abono with the amount originally applied.
        await revert_card_payment(session, space.id, txn, old_applied)

    if resolved.target is not None and resolved.target_behavior == AccountBehavior.credit:
        # TXN-09: an edit to the same card keeps the payment on its original
        # statement unless the client targets another one explicitly.
        target = data.target_statement_id
        if target is None and was_tdc_payment and old_account_to_id == txn.account_to_id:
            target = old_statement_id
        await apply_card_payment(session, space, resolved.target, txn, target)
    elif await _assign_credit_charge(session, resolved, txn, data.cycle_hint) is None:
        # Not a credit charge any more: clear a stale statement link.
        txn.statement_id = None

    await session.flush()
    # Recompute charge statements that changed (TDC-05; payments keep paid_amount).
    if not was_tdc_payment:
        if old_statement_id is not None and old_statement_id != txn.statement_id:
            await recompute_statement_total(session, old_statement_id)
        if txn.statement_id is not None and txn.type != TransactionType.transfer:
            await recompute_statement_total(session, txn.statement_id)

    # TXN-14: the fee is rebuilt from the edited transfer.
    await _drop_fee(session, txn)
    if data.type == TransactionType.transfer and data.fee_amount is not None:
        await _create_fee(session, space, updated_by, txn, resolved, data.fee_amount)

    await session.commit()
    await session.refresh(txn)
    return txn


async def delete_transaction(session: AsyncSession, space_id: uuid.UUID, txn_id: uuid.UUID) -> None:
    from app.services.accounts import received_amount, recompute_statement_total

    txn = await get_transaction(session, space_id, txn_id)
    _reject_fee_row(txn)
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
    if txn.type == TransactionType.transfer and old_statement_id is not None:
        # TXN-09: deleting a TDC payment takes its abono back off the statement.
        from app.services.accounts import revert_card_payment

        await revert_card_payment(session, space_id, txn, received_amount(txn))
        old_statement_id = None
    await _drop_fee(session, txn)  # TXN-14
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
