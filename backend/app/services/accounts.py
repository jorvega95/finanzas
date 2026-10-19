"""Accounts and credit statements. Implements TAR-01..TAR-10, TDC-01..TDC-16,
MSI-05, REM-01.

The pure cycle math lives in services/billing_cycles.py; this module owns
persistence: accounts, balances (TAR-05/TAR-09), statement materialization
(TDC-11), charge assignment (TDC-05/TXN-06), closing (TDC-07), payments
(TDC-10) and debt (TDC-09).
"""

import uuid
from collections.abc import Collection
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.core.text import normalize_name
from app.models.accounts import Account, AccountLayout, Statement, StatementStatus
from app.models.catalogs import (
    ALWAYS_OVERDRAFT_BEHAVIORS,
    BALANCE_BEHAVIORS,
    AccountBehavior,
    AccountType,
    Category,
    CategoryKind,
    ExpenseNature,
)
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus, PlanStatus
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import billing_cycles as cycles

ZERO = Decimal("0.00")
FEES_CATEGORY_NAME = "Comisiones e intereses"  # TDC-13


def spec_for(account: Account) -> cycles.CardCycleSpec:
    return cycles.CardCycleSpec(
        statement_day="last" if account.statement_day_is_last else (account.statement_day or 1),
        # str() works whether the attribute holds the StrEnum member or a raw
        # string not yet round-tripped through the DB (e.g. just-built account).
        cutoff_day_policy=str(account.cutoff_day_policy),
        payment_due_days=account.payment_due_days,
        payment_day="last"
        if account.payment_day_is_last
        else account.payment_day
        if account.payment_day is not None
        else None,
    )


async def get_account(session: AsyncSession, space_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = await session.get(Account, account_id)
    if account is None or account.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    return account


# --- TAR-07: per-user account ordering --------------------------------------------


async def get_account_layout(
    session: AsyncSession, user_id: uuid.UUID, space_id: uuid.UUID
) -> AccountLayout | None:
    layout: AccountLayout | None = await session.scalar(
        select(AccountLayout).where(
            AccountLayout.user_id == user_id, AccountLayout.space_id == space_id
        )
    )
    return layout


def order_accounts(accounts: list[Account], layout_ids: list[str]) -> list[Account]:
    """TAR-07: order `accounts` by the user's saved layout; accounts not in the layout
    keep name order at the end. Pure list ordering (not a SQL aggregate), so it
    doesn't fall under DSH-03."""
    position = {cid: i for i, cid in enumerate(layout_ids)}
    end = len(layout_ids)
    return sorted(accounts, key=lambda c: (position.get(str(c.id), end), c.name))


async def set_account_layout(
    session: AsyncSession,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    account_ids: list[uuid.UUID],
) -> None:
    """TAR-07: upsert the user's ordered list for the space, dropping ids that
    don't belong to the space (defensive)."""
    valid = set(
        (await session.execute(select(Account.id).where(Account.space_id == space_id)))
        .scalars()
        .all()
    )
    ordered = [str(cid) for cid in account_ids if cid in valid]
    layout = await get_account_layout(session, user_id, space_id)
    if layout is None:
        session.add(AccountLayout(user_id=user_id, space_id=space_id, account_ids=ordered))
    else:
        layout.account_ids = ordered
    await session.commit()


async def ensure_fees_category(
    session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID
) -> Category:
    """TDC-13/TXN-14: 'Comisiones e intereses', seeded with the first credit
    account or the first transfer fee."""
    normalized = normalize_name(FEES_CATEGORY_NAME)
    category: Category | None = await session.scalar(
        select(Category).where(
            Category.space_id == space_id,
            Category.kind == CategoryKind.expense,
            Category.name_normalized == normalized,
        )
    )
    if category is None:
        category = Category(
            space_id=space_id,
            name=FEES_CATEGORY_NAME,
            name_normalized=normalized,
            kind=CategoryKind.expense,
            expense_nature=ExpenseNature.fixed,
            created_by=created_by,
        )
        session.add(category)
        await session.flush()
    return category


async def _unique_account_name(
    session: AsyncSession,
    space_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """CAT-01: account name unique per space, case/accent-insensitive."""
    normalized = normalize_name(name)
    stmt = select(Account.id).where(
        Account.space_id == space_id, Account.name_normalized == normalized
    )
    if exclude_id is not None:
        stmt = stmt.where(Account.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese nombre")
    return normalized


def _validate_last4(last4: object) -> None:
    """TDC-01/TAR-02: optional, but exactly 4 digits when present."""
    if last4 is not None and not (isinstance(last4, str) and last4.isdigit() and len(last4) == 4):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "last4 debe ser 4 dígitos")


async def has_movements(session: AsyncSession, account_id: uuid.UUID) -> bool:
    """Whether any transaction touches the account (source or target)."""
    found = await session.scalar(
        select(Transaction.id)
        .where((Transaction.account_id == account_id) | (Transaction.account_to_id == account_id))
        .limit(1)
    )
    return found is not None


def cycle_ready(account: Account) -> bool:
    """TDC-15: a credit account runs its cycle engine only once it has a cut day.
    Until then its charges are not assigned to any statement."""
    return account.statement_day is not None or account.statement_day_is_last


def _payment_ready(account: Account) -> bool:
    """A account has its payment terms set (needed to compute a due_date)."""
    return (
        account.payment_due_days is not None
        or account.payment_day is not None
        or account.payment_day_is_last
    )


def _resolve_credit_fields(
    statement_day: int | str | None,
    payment_due_days: int | None,
    payment_day: int | str | None,
) -> dict[str, object]:
    """TDC-01/TDC-15: validate the (optional) cycle config. Fields may be left
    unset for a partially-captured account; at most one payment rule is allowed."""
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
    session: AsyncSession, space: Space, account: Account
) -> Decimal | None:
    """TDC-14: return the computed_total of the synthetic opening-balance statement
    (previous period, no itemized charges), or None if no such statement exists."""
    if not (cycle_ready(account) and _payment_ready(account)):
        return None
    spec = spec_for(account)
    today = today_in_tz(space.timezone)
    opening_cutoff = cycles.previous_cutoff(cycles.cutoff_on_or_after(today, spec), spec)
    _, period_end = cycles.cycle_for_cutoff(opening_cutoff, spec)
    existing = await session.scalar(
        select(Statement).where(
            Statement.account_id == account.id,
            Statement.period_end == period_end,
        )
    )
    if existing is None:
        return None
    if await _statement_has_charges(session, existing.id):
        return None
    return existing.opening_balance


async def set_opening_balance(
    session: AsyncSession, space: Space, account: Account, amount: Decimal
) -> Statement | None:
    """TDC-14: record the pending debt from the previous cut as a closed
    statement (due at the next payment date) so it enters TDC-09 (saldo al
    corte) and is paid via TDC-10. Create-or-update on the previous cut; never
    overwrite a cut that already has itemized charges. Usable at alta and edit.

    REM-01: schedules future reminders for the statement; cancels existing
    ones when amount is zeroed out."""
    from app.services.reminders import cancel_card_reminders, schedule_card_reminders

    if not (cycle_ready(account) and _payment_ready(account)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Para registrar deuda inicial configura el día de corte y los términos de pago",
        )
    spec = spec_for(account)
    today = today_in_tz(space.timezone)
    opening_cutoff = cycles.previous_cutoff(cycles.cutoff_on_or_after(today, spec), spec)
    period_start, period_end = cycles.cycle_for_cutoff(opening_cutoff, spec)

    existing = await session.scalar(
        select(Statement).where(
            Statement.account_id == account.id,
            Statement.period_end == period_end,
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
        existing.opening_balance = amount
        existing.computed_total = amount
        existing.status = StatementStatus.closed
        _update_payment_status(existing)
        await session.flush()
        if amount == ZERO:
            await cancel_card_reminders(session, existing)
        else:
            await schedule_card_reminders(session, account, existing, today)
        return existing

    statement = Statement(
        space_id=space.id,
        account_id=account.id,
        period_start=period_start,
        period_end=period_end,
        due_date=cycles.due_date_for(period_end, spec),
        computed_total=amount,
        opening_balance=amount,
        paid_amount=ZERO,
        status=StatementStatus.closed,
    )
    session.add(statement)
    await session.flush()
    # REM-01: schedule reminders for the new statement; filter past fire dates.
    await schedule_card_reminders(session, account, statement, today)
    return statement


async def next_payment_due(session: AsyncSession, account: Account) -> tuple[Decimal, date] | None:
    """TDC-09/TDC-14: the nearest closed (unpaid) statement to settle — the
    amount due at the upcoming payment date."""
    statements = (
        (
            await session.execute(
                select(Statement)
                .where(
                    Statement.account_id == account.id,
                    Statement.status.in_([StatementStatus.closed, StatementStatus.partially_paid]),
                )
                .order_by(Statement.due_date)
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


async def create_account(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    account_type_id: uuid.UUID,
    name: str,
    bank: str | None = None,
    network: str | None = None,
    last4: str | None = None,
    currency: str = "MXN",
    # TAR-02 credit-only fields (all optional, TDC-15: may be filled later).
    statement_day: int | str | None = None,
    cutoff_day_policy: str = "include",
    payment_due_days: int | None = None,
    payment_day: int | str | None = None,
    credit_limit: Decimal | None = None,
    reminder_days: list[int] | None = None,
    opening_balance: Decimal | None = None,  # TDC-14: deuda del corte anterior
    # TAR-05 balance fields.
    initial_balance: Decimal | None = None,
    allow_overdraft: bool = False,
    color: str | None = None,
    image: str | None = None,  # TAR-08
) -> Account:
    """TAR-01/02 + TDC-01: creates an account. Credit accounts carry (optional)
    cycle fields and an optional opening debt (TDC-14); the rest carry a
    balance (TAR-05). Cash always allows overdraft (TAR-09)."""
    from app.services.catalogs import get_account_type

    _validate_last4(last4)
    account_type = await get_account_type(session, space.id, account_type_id)  # GLO-05
    behavior = account_type.behavior
    name_normalized = await _unique_account_name(session, space.id, name)
    common: dict[str, object] = {
        "space_id": space.id,
        "account_type_id": account_type_id,
        "name": name,
        "name_normalized": name_normalized,
        "bank": bank,
        "network": network,
        "last4": last4,
        "currency": currency,
        "color": color,
        "image": image,
        "created_by": created_by,
    }

    _validate_initial_balance(behavior, initial_balance)
    if behavior == AccountBehavior.credit:
        # TDC-15: cycle fields are optional and can be completed later via edit.
        if initial_balance is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Una tarjeta de crédito no lleva saldo inicial",
            )
        cfg = _resolve_credit_fields(statement_day, payment_due_days, payment_day)
        account = Account(
            **common,
            credit_limit=credit_limit,
            cutoff_day_policy=cutoff_day_policy,
            reminder_days=reminder_days if reminder_days is not None else [3, 1],
            **cfg,
        )
    else:
        # TAR-02: balance accounts must not carry credit fields.
        if any(
            v is not None
            for v in (statement_day, payment_due_days, payment_day, credit_limit, opening_balance)
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Solo las tarjetas de crédito llevan campos de corte/pago/límite/deuda",
            )
        account = Account(
            **common,
            initial_balance=initial_balance if initial_balance is not None else ZERO,
            # TAR-09/TAR-11: cash and loans always allow overdraft.
            allow_overdraft=True if behavior in ALWAYS_OVERDRAFT_BEHAVIORS else allow_overdraft,
            reminder_days=[],
        )
    session.add(account)
    await session.flush()
    if behavior == AccountBehavior.credit:
        await ensure_fees_category(session, space.id, created_by)  # TDC-13
        if opening_balance is not None and opening_balance > ZERO:
            await set_opening_balance(session, space, account, opening_balance)  # TDC-14
    await session.commit()
    await session.refresh(account)
    return account


def _validate_initial_balance(behavior: AccountBehavior, value: Decimal | None) -> None:
    """TAR-05/TAR-11: only a loan opens with a negative balance (what you owe)."""
    if value is not None and value < ZERO and behavior != AccountBehavior.loan:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El saldo inicial no puede ser negativo",
        )


async def update_account(
    session: AsyncSession, space: Space, account: Account, changes: dict[str, object]
) -> Account:
    """TDC-15: full edit of an account (like a transaction edit). Re-validates
    the fields present in `changes`, behavior-aware. Type/behavior is fixed."""
    behavior = await account_behavior(session, account)
    credit_only = {
        "statement_day",
        "cutoff_day_policy",
        "payment_due_days",
        "payment_day",
        "credit_limit",
        "reminder_days",
    }
    balance_only = {"initial_balance", "allow_overdraft"}
    if behavior != AccountBehavior.credit and credit_only & changes.keys():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Esta cuenta no lleva campos de corte/pago/límite",
        )
    if behavior == AccountBehavior.credit and balance_only & changes.keys():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Una tarjeta de crédito no lleva saldo"
        )
    if behavior in ALWAYS_OVERDRAFT_BEHAVIORS:
        changes.pop("allow_overdraft", None)  # TAR-09/TAR-11: always allowed.
    if "initial_balance" in changes:
        _validate_initial_balance(behavior, changes["initial_balance"])  # type: ignore[arg-type]
    if "last4" in changes:
        _validate_last4(changes["last4"])
    if "name" in changes:
        account.name_normalized = await _unique_account_name(
            session, space.id, str(changes["name"]), exclude_id=account.id
        )
    if (
        "currency" in changes
        and changes["currency"] != account.currency
        and await has_movements(session, account.id)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "La cuenta ya tiene movimientos; no se puede cambiar su moneda",
        )  # TAR-10

    # Re-derive the cycle config if any cut/payment field changed (TDC-15).
    if (
        behavior == AccountBehavior.credit
        and {
            "statement_day",
            "payment_due_days",
            "payment_day",
        }
        & changes.keys()
    ):
        cur_sd: int | str | None = (
            "last" if account.statement_day_is_last else account.statement_day
        )
        cur_pd: int | str | None = "last" if account.payment_day_is_last else account.payment_day
        eff_sd = changes["statement_day"] if "statement_day" in changes else cur_sd
        eff_pdd = (
            changes["payment_due_days"]
            if "payment_due_days" in changes
            else account.payment_due_days
        )
        eff_pd = changes["payment_day"] if "payment_day" in changes else cur_pd
        for key, value in _resolve_credit_fields(eff_sd, eff_pdd, eff_pd).items():  # type: ignore[arg-type]
            setattr(account, key, value)

    for field in (
        "name",
        "bank",
        "network",
        "last4",
        "currency",
        "color",
        "image",  # TAR-08
        "cutoff_day_policy",
        "credit_limit",
        "reminder_days",
        "initial_balance",
        "allow_overdraft",
    ):
        if field in changes:
            setattr(account, field, changes[field])

    # TDC-14: pending balance from the previous cut (credit only). Applied last
    # so it reads any cut/payment fields updated in this same edit.
    if "opening_balance" in changes:
        if behavior != AccountBehavior.credit:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Solo las tarjetas de crédito llevan deuda del corte anterior",
            )
        amount = changes["opening_balance"]
        if isinstance(amount, Decimal) and amount >= ZERO:
            await set_opening_balance(session, space, account, amount)

    await session.commit()
    await session.refresh(account)
    return account


async def set_account_active(session: AsyncSession, account: Account, active: bool) -> None:
    """CAT-04/TDC-12: (de)activate an account. CAT-05: never the last active one."""
    if not active and account.is_active:
        active_count = await session.scalar(
            select(func.count())
            .select_from(Account)
            .where(Account.space_id == account.space_id, Account.is_active.is_(True))
        )
        if (active_count or 0) <= 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "No puedes desactivar la última cuenta activa",
            )
    account.is_active = active
    await session.commit()


async def account_behavior(session: AsyncSession, account: Account) -> AccountBehavior:
    """TAR-01: the account's behavior, read from its type (CAT-08)."""
    account_type = await session.get(AccountType, account.account_type_id)
    assert account_type is not None
    return account_type.behavior


def balance_predicates(account_id: uuid.UUID) -> dict[str, list[ColumnElement[bool]]]:
    """TAR-05: the four flows of a balance account. Shared by account_balance
    and the forecast's as-of balance (DSH-03: predicates in one place)."""
    return {
        "income": [
            Transaction.type == TransactionType.income,
            Transaction.account_id == account_id,
        ],
        "transfer_in": [
            Transaction.type == TransactionType.transfer,
            Transaction.account_to_id == account_id,
        ],
        "expense": [
            Transaction.type == TransactionType.expense,
            Transaction.account_id == account_id,
            Transaction.installment_plan_id.is_(None),  # MSI parent excluded
        ],
        "transfer_out": [
            Transaction.type == TransactionType.transfer,
            Transaction.account_id == account_id,
        ],
    }


# TXN-13: an incoming transfer adds what was received, in the target currency.
RECEIVED_AMOUNT = func.coalesce(Transaction.amount_to, Transaction.amount)


async def account_balance(
    session: AsyncSession,
    account: Account,
    exclude_txn_ids: Collection[uuid.UUID] = (),
    as_of: date | None = None,
) -> Decimal:
    """TAR-05: stored-value balance, computed in SQL: initial + income +
    incoming transfers (received amount) − expenses − outgoing transfers.
    `exclude_txn_ids` ignores transactions (an edit and its fee, while
    validating it); `as_of` bounds it to movements dated up to that day (PRO-02)."""
    scope: list[ColumnElement[bool]] = [Transaction.space_id == account.space_id]
    if exclude_txn_ids:
        scope.append(Transaction.id.not_in(list(exclude_txn_ids)))
    if as_of is not None:
        scope.append(Transaction.date <= as_of)

    flows = balance_predicates(account.id)

    async def total(key: str) -> Decimal:
        column = RECEIVED_AMOUNT if key == "transfer_in" else Transaction.amount
        value = await session.scalar(
            select(func.coalesce(func.sum(column), 0)).where(*scope, *flows[key])
        )
        return Decimal(value or 0)

    initial = Decimal(account.initial_balance if account.initial_balance is not None else 0)
    return (
        initial
        + await total("income")
        + await total("transfer_in")
        - await total("expense")
        - await total("transfer_out")
    )


async def adjust_cash_balance(session: AsyncSession, account: Account, target: Decimal) -> None:
    """TAR-09: set a cash account's balance to what the user really has by
    shifting initial_balance. No transaction is created and no aggregate moves:
    lost or unrecorded cash doesn't become an invented expense."""
    if await account_behavior(session, account) != AccountBehavior.cash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Solo el efectivo se ajusta a mano; las demás cuentas se cuadran "
            "con su estado de cuenta",
        )
    current = await account_balance(session, account)
    initial = Decimal(account.initial_balance if account.initial_balance is not None else 0)
    account.initial_balance = initial + (target - current)
    await session.commit()


async def deactivate_account(session: AsyncSession, account: Account) -> None:
    """TDC-12: no new charges, but cycles keep closing until settled."""
    await set_account_active(session, account, False)


async def delete_account(session: AsyncSession, account: Account) -> None:
    """GLO-03: physical delete only without references (movements, statements,
    MSI plans); otherwise the client deactivates it. CAT-05 still applies."""
    has_statements = await session.scalar(
        select(Statement.id).where(Statement.account_id == account.id).limit(1)
    )
    has_plans = await session.scalar(
        select(InstallmentPlan.id).where(InstallmentPlan.account_id == account.id).limit(1)
    )
    if await has_movements(session, account.id) or has_statements or has_plans:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "La cuenta tiene movimientos asociados; desactívala en su lugar",
        )
    if account.is_active:
        await set_account_active(session, account, False)  # CAT-05 guard
    await session.delete(account)
    await session.commit()


# --- Statements ----------------------------------------------------------------


async def get_or_create_statement(
    session: AsyncSession, account: Account, cutoff: date
) -> Statement:
    """TDC-11: statements materialize on demand, never in advance."""
    existing = await session.scalar(
        select(Statement).where(
            Statement.account_id == account.id,
            Statement.period_end == cutoff,
        )
    )
    if existing is not None:
        return existing
    spec = spec_for(account)
    period_start, period_end = cycles.cycle_for_cutoff(cutoff, spec)
    statement = Statement(
        space_id=account.space_id,
        account_id=account.id,
        period_start=period_start,
        period_end=period_end,
        due_date=cycles.due_date_for(period_end, spec),
    )
    session.add(statement)
    await session.flush()
    return statement


async def assign_charge_to_statement(
    session: AsyncSession,
    account: Account,
    txn: Transaction,
    cycle_hint: str | None = None,
) -> Statement:
    """TDC-05/TXN-06: assign a credit charge to its billing cycle.

    TDC-05a: if cycle_hint ('current'|'next') is provided and the transaction
    date falls exactly on the cutoff day, it overrides cutoff_day_policy.
    """
    spec = spec_for(account)
    if cycle_hint is not None:
        override = "include" if cycle_hint == "current" else "next_cycle"
        spec = cycles.CardCycleSpec(
            statement_day=spec.statement_day,
            cutoff_day_policy=override,
            payment_due_days=spec.payment_due_days,
            payment_day=spec.payment_day,
        )
    _, cutoff = cycles.cycle_for_purchase(txn.date, spec)
    statement = await get_or_create_statement(session, account, cutoff)
    txn.statement_id = statement.id
    return statement


async def assign_refund_to_statement(
    session: AsyncSession, account: Account, txn: Transaction
) -> Statement:
    """TDC-16: a refund (income) posted after a statement's cutoff but on/before
    its due_date reduces that pending statement instead of the next cycle,
    mirroring how a bank applies a late refund to the bill already issued."""
    candidates = (
        (
            await session.execute(
                select(Statement)
                .where(
                    Statement.account_id == account.id,
                    Statement.status.in_([StatementStatus.closed, StatementStatus.partially_paid]),
                    Statement.period_end < txn.date,
                    Statement.due_date >= txn.date,
                )
                .order_by(Statement.period_end)
            )
        )
        .scalars()
        .all()
    )
    for statement in candidates:
        if statement.computed_total - statement.paid_amount > ZERO:
            txn.statement_id = statement.id
            return statement
    return await assign_charge_to_statement(session, account, txn)


async def get_statement(
    session: AsyncSession, space_id: uuid.UUID, statement_id: uuid.UUID
) -> Statement:
    statement = await session.get(Statement, statement_id)
    if statement is None or statement.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement no encontrado")
    return statement


async def _raw_statement_total(session: AsyncSession, statement: Statement) -> Decimal:
    """Opening balance + charges − refunds + MSI installments charged into
    this statement.

    MSI-03: parent purchases (installment_plan_id != NULL) are excluded; their
    installments enter instead. Payments (transfers) live in paid_amount.
    TDC-14 (PEND-01): opening_balance is kept separate from itemized charges
    so a late charge/refund landing on a manual-opening-balance statement adds
    to it instead of silently replacing it.
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
    opening = Decimal(statement.opening_balance) if statement.opening_balance is not None else ZERO
    return opening + Decimal(charges or 0) - Decimal(refunds or 0) + Decimal(msi or 0)


async def recompute_statement_total(session: AsyncSession, statement_id: uuid.UUID) -> None:
    """Recompute a closed statement after charge edits/moves (TDC-06)."""
    statement = await session.get(Statement, statement_id)
    if statement is None or statement.status == StatementStatus.open:
        return
    statement.computed_total = (
        await _raw_statement_total(session, statement) - statement.applied_credit
    )
    _update_payment_status(statement)
    await session.flush()


def _update_payment_status(statement: Statement) -> None:
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
) -> list[Statement]:
    """TDC-07: close every open statement with period_end < today. Closing:
    assigns due MSI installments (MSI-04/05), applies previous overpayment
    (TDC-10), computes the total and schedules reminders (REM-01).
    Idempotent: already-closed statements are skipped."""
    from app.services.reminders import schedule_card_reminders

    today = today or today_in_tz(space.timezone)
    closed: list[Statement] = []

    # TAR-04: only credit accounts have statements/cycles.
    # TDC-15: skip credit accounts without a cut day configured yet.
    accounts = (
        (
            await session.execute(
                select(Account)
                .join(AccountType, Account.account_type_id == AccountType.id)
                .where(
                    Account.space_id == space.id,
                    AccountType.behavior == AccountBehavior.credit,
                    Account.statement_day.is_not(None) | Account.statement_day_is_last.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for account in accounts:
        spec = spec_for(account)
        # Materialize any statement whose cycle already ended (covers gaps
        # since the earliest charge thanks to on-demand creation TDC-11).
        while True:
            open_statements = (
                (
                    await session.execute(
                        select(Statement)
                        .where(
                            Statement.account_id == account.id,
                            Statement.status == StatementStatus.open,
                            Statement.period_end < today,
                        )
                        .order_by(Statement.period_end)
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
                                InstallmentPlan.account_id == account.id,
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
                    select(Statement)
                    .where(
                        Statement.account_id == account.id,
                        Statement.period_end < statement.period_end,
                        Statement.status != StatementStatus.open,
                    )
                    .order_by(Statement.period_end.desc())
                    .limit(1)
                )
                credit = ZERO
                if previous is not None:
                    credit = max(previous.paid_amount - previous.computed_total, ZERO)
                statement.applied_credit = credit
                statement.computed_total = await _raw_statement_total(session, statement) - credit
                statement.status = StatementStatus.closed
                _update_payment_status(statement)
                # REM-01: pass today so past fire dates are skipped.
                await schedule_card_reminders(session, account, statement, today)
                closed.append(statement)
            await session.flush()

        # Keep one open statement materialized for the current cycle.
        current_cutoff = cycles.cutoff_on_or_after(today, spec)
        await get_or_create_statement(session, account, current_cutoff)

    await session.commit()
    return closed


# --- Payments (TDC-10 / TXN-09) -------------------------------------------------


def received_amount(txn: Transaction) -> Decimal:
    """TXN-09/TXN-13: what a transfer delivers to its target account."""
    return txn.amount_to if txn.amount_to is not None else txn.amount


async def apply_card_payment(
    session: AsyncSession,
    space: Space,
    account: Account,
    txn: Transaction,
    target_statement_id: uuid.UUID | None = None,
) -> None:
    """TXN-09/TDC-10: assign txn to a statement and abono paid_amount.

    Resolves the statement: explicit target_statement_id → that one (validated);
    else oldest unpaid closed statement; else open current cycle.
    Called from create_transaction (TXN-09) and from register_payment (TDC-10).
    Does NOT commit — caller is responsible."""
    from app.services.reminders import cancel_card_reminders

    if not cycle_ready(account):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Configura el día de corte de la tarjeta antes de registrar pagos",
        )

    if target_statement_id is not None:
        statement = await get_statement(session, space.id, target_statement_id)
        if statement.account_id != account.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement no encontrado")
    else:
        candidate = await session.scalar(
            select(Statement)
            .where(
                Statement.account_id == account.id,
                Statement.status.in_([StatementStatus.closed, StatementStatus.partially_paid]),
            )
            .order_by(Statement.period_end)
            .limit(1)
        )
        if candidate is None:
            cutoff = cycles.cutoff_on_or_after(today_in_tz(space.timezone), spec_for(account))
            candidate = await get_or_create_statement(session, account, cutoff)
        statement = candidate

    txn.statement_id = statement.id
    statement.paid_amount = statement.paid_amount + received_amount(txn)
    _update_payment_status(statement)
    await session.flush()

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


async def revert_card_payment(
    session: AsyncSession, space_id: uuid.UUID, txn: Transaction, applied_amount: Decimal
) -> None:
    """Undo a previously applied TDC payment (TXN-09 update path).

    When editing a transfer that was already applied to a statement, subtract
    the amount originally applied (`applied_amount`, captured before the edit
    mutates `txn.amount`) from paid_amount and re-evaluate the statement status."""
    if txn.statement_id is None:
        return
    statement = await session.get(Statement, txn.statement_id)
    if statement is None or statement.space_id != space_id:
        return
    statement.paid_amount = max(statement.paid_amount - applied_amount, ZERO)
    _update_payment_status(statement)
    txn.statement_id = None
    await session.flush()


async def register_payment(
    session: AsyncSession,
    space: Space,
    user_id: uuid.UUID,
    account: Account,
    *,
    amount: Decimal,
    from_account_id: uuid.UUID,
    payment_date: date,
    statement_id: uuid.UUID | None = None,
) -> Transaction:
    """TDC-10: a card payment is a transfer (TXN-02) into the credit account.
    Delegates payment accounting to apply_card_payment via create_transaction.
    TAR-10: the transfer goes in the source account's currency."""
    from app.services.transactions import TransactionInput, create_transaction

    source = await get_account(session, space.id, from_account_id)
    return await create_transaction(
        session,
        space,
        user_id,
        TransactionInput(
            type=TransactionType.transfer,
            date=payment_date,
            amount=amount,
            currency=source.currency,
            description=f"Pago {account.name}",
            account_id=source.id,
            account_to_id=account.id,
            target_statement_id=statement_id,
        ),
    )


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


async def debt_summary(session: AsyncSession, account: Account) -> dict[str, Decimal]:
    """TDC-09: (a) saldo al corte, (b) gasto del ciclo en curso,
    (c) comprometido futuro MSI. Deuda total = a + b + c."""
    closed_unpaid = (
        (
            await session.execute(
                select(Statement).where(
                    Statement.account_id == account.id,
                    Statement.status.in_([StatementStatus.closed, StatementStatus.partially_paid]),
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
                select(Statement).where(
                    Statement.account_id == account.id,
                    Statement.status == StatementStatus.open,
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
            InstallmentPlan.account_id == account.id,
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


# --- Signed balance (TAR-06) -----------------------------------------------------


async def account_signed_balance(session: AsyncSession, account: Account) -> Decimal | None:
    """TAR-06: asset-perspective balance with sign.

    balance accounts → +account_balance() (asset; negative if overdrawn)
    loan             → +account_balance() (negative = debt, positive = receivable)
    credit           → -(total_debt) (liability), null if not cycle-ready
    """
    behavior = await account_behavior(session, account)
    if behavior in BALANCE_BEHAVIORS:
        return await account_balance(session, account)
    if not cycle_ready(account):
        return None
    summary = await debt_summary(session, account)
    return -summary["total_debt"]


# --- Reassignment (TDC-06) -------------------------------------------------------


async def move_charge_cycle(
    session: AsyncSession,
    space: Space,
    user_id: uuid.UUID,
    txn: Transaction,
    direction: str,
) -> Transaction:
    """TDC-06: move a charge one cycle back/forward; recompute both statements."""
    if txn.statement_id is None or txn.account_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El cargo no tiene ciclo")
    if direction not in ("prev", "next"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "direction: prev | next")

    account = await get_account(session, space.id, txn.account_id)
    spec = spec_for(account)
    current = await get_statement(session, space.id, txn.statement_id)
    if direction == "prev":
        target_cutoff = cycles.previous_cutoff(current.period_end, spec)
    else:
        target_cutoff = cycles.next_cutoff(current.period_end, spec)
    target = await get_or_create_statement(session, account, target_cutoff)

    old_id = txn.statement_id
    txn.statement_id = target.id
    txn.updated_by = user_id  # TDC-06: auditada
    await session.flush()
    await recompute_statement_total(session, old_id)
    await recompute_statement_total(session, target.id)
    await session.commit()
    await session.refresh(txn)
    return txn
