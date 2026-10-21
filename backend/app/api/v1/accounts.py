"""Router: accounts, statements and payments. Implements TAR-01..TAR-10,
TDC-01..TDC-12, REM-04."""

import datetime as dt
import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.v1.transactions import transaction_out
from app.core.dates import today_in_tz
from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.accounts import Account, Statement, StatementStatus
from app.models.catalogs import BALANCE_BEHAVIORS, AccountBehavior
from app.models.spaces import Space
from app.schemas.accounts import (
    AccountCreate,
    AccountLayoutOut,
    AccountLayoutUpdate,
    AccountOut,
    AccountUpdate,
    AccountWithDebtOut,
    CashBalanceAdjust,
    DebtSummary,
    NextPaymentOut,
    PaymentCreate,
    StatementOut,
)
from app.schemas.transactions import TransactionOut
from app.services import accounts as svc
from app.services import fx
from app.services.reminders import fire_due_reminders

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _statement_out(statement: Statement, today: dt.date) -> StatementOut:
    out = StatementOut.model_validate(statement)
    # TDC-08: overdue is a flag computed against today, not a status.
    out.is_overdue = (
        statement.status in (StatementStatus.closed, StatementStatus.partially_paid)
        and today > statement.due_date
    )
    return out


async def _account_with_debt(db: DbSession, space: Space, account: Account) -> AccountWithDebtOut:
    out = AccountWithDebtOut.model_validate(account)
    out.behavior = await svc.account_behavior(db, account)
    if out.behavior == AccountBehavior.credit:
        out.debt = DebtSummary(**(await svc.debt_summary(db, account)))  # TDC-09
        nxt = await svc.next_payment_due(db, account)  # TDC-14
        if nxt is not None:
            amount, due_date = nxt
            out.next_payment = NextPaymentOut(amount=amount, due_date=due_date)
        out.opening_balance = await svc.get_opening_balance(db, space, account)  # TDC-14
    elif out.behavior in BALANCE_BEHAVIORS:
        out.balance = await svc.account_balance(db, account)  # TAR-05
        if account.currency != space.base_currency:  # TAR-12
            today = today_in_tz(space.timezone)
            rate = await fx.get_rate(db, account.currency, space.base_currency, today)
            if rate is not None:
                out.balance_fx_rate = rate
                out.balance_base = await fx.mark_to_market(
                    db, out.balance, account.currency, space.base_currency, today
                )
    out.signed_balance = await svc.account_signed_balance(db, account)  # TAR-06
    return out


@router.get("", response_model=list[AccountWithDebtOut])
async def list_accounts(
    db: DbSession,
    space_and_member: ActiveSpace,
    user: CurrentUser,
    include_inactive: bool = False,
) -> list[AccountWithDebtOut]:
    space, _ = space_and_member
    stmt = select(Account).where(Account.space_id == space.id)
    if not include_inactive:
        stmt = stmt.where(Account.is_active.is_(True))
    accounts = list((await db.execute(stmt.order_by(Account.name))).scalars().all())
    # TAR-07: apply the user's personal ordering on top of the name baseline.
    layout = await svc.get_account_layout(db, user.id, space.id)
    accounts = svc.order_accounts(accounts, layout.account_ids if layout else [])
    return [await _account_with_debt(db, space, account) for account in accounts]


@router.get("/layout", response_model=AccountLayoutOut)
async def get_account_layout(
    db: DbSession, space_and_member: ActiveSpace, user: CurrentUser
) -> AccountLayoutOut:
    """TAR-07: the current user's account and section order for the active space."""
    space, _ = space_and_member
    layout = await svc.get_account_layout(db, user.id, space.id)
    return AccountLayoutOut(
        account_ids=[uuid.UUID(i) for i in (layout.account_ids if layout else [])],
        group_order=svc.resolve_group_order(layout.group_order if layout else None),
    )


@router.put("/layout", status_code=status.HTTP_204_NO_CONTENT)
async def set_account_layout(
    db: DbSession,
    space_and_member: ActiveSpace,
    user: CurrentUser,
    payload: AccountLayoutUpdate,
) -> None:
    """TAR-07: save the current user's account order for the active space. Personal
    UI preference (not shared domain data), so any member may set it — ActiveSpace,
    not EditorSpace. Non-members get 404 upstream (GLO-05)."""
    space, _ = space_and_member
    await svc.set_account_layout(db, user.id, space.id, payload.account_ids, payload.group_order)


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: AccountCreate
) -> Account:
    space, _ = space_and_member
    return await svc.create_account(
        db,
        space,
        user.id,
        account_type_id=payload.account_type_id,
        name=payload.name,
        bank=payload.bank,
        network=payload.network,
        last4=payload.last4,
        currency=payload.currency,
        statement_day=payload.statement_day,
        cutoff_day_policy=payload.cutoff_day_policy.value,
        payment_due_days=payload.payment_due_days,
        payment_day=payload.payment_day,
        credit_limit=payload.credit_limit,
        reminder_days=payload.reminder_days,
        opening_balance=payload.opening_balance,
        initial_balance=payload.initial_balance,
        allow_overdraft=payload.allow_overdraft,
        color=payload.color,
        image=payload.image,
    )


@router.get("/{account_id}", response_model=AccountWithDebtOut)
async def get_account(
    db: DbSession, space_and_member: ActiveSpace, account_id: uuid.UUID
) -> AccountWithDebtOut:
    space, _ = space_and_member
    account = await svc.get_account(db, space.id, account_id)
    return await _account_with_debt(db, space, account)


@router.patch("/{account_id}", response_model=AccountWithDebtOut)
async def update_account(
    db: DbSession,
    space_and_member: EditorSpace,
    account_id: uuid.UUID,
    payload: AccountUpdate,
) -> AccountWithDebtOut:
    """TDC-15: full edit; fields left blank at creation can be filled later."""
    space, _ = space_and_member
    account = await svc.get_account(db, space.id, account_id)
    changes = payload.model_dump(exclude_unset=True)
    is_active = changes.pop("is_active", None)
    if is_active is False:
        await svc.deactivate_account(db, account)  # TDC-12, CAT-05
    elif is_active is True:
        await svc.set_account_active(db, account, True)
    if changes:
        await svc.update_account(db, space, account, changes)
    await db.refresh(account)
    return await _account_with_debt(db, space, account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    db: DbSession, space_and_member: EditorSpace, account_id: uuid.UUID
) -> None:
    """GLO-03: delete an account that was never used; otherwise 409."""
    space, _ = space_and_member
    account = await svc.get_account(db, space.id, account_id)
    await svc.delete_account(db, account)


@router.post("/{account_id}/balance", response_model=AccountWithDebtOut)
async def adjust_balance(
    db: DbSession,
    space_and_member: EditorSpace,
    account_id: uuid.UUID,
    payload: CashBalanceAdjust,
) -> AccountWithDebtOut:
    """TAR-09: set a cash account's balance to the real cash on hand."""
    space, _ = space_and_member
    account = await svc.get_account(db, space.id, account_id)
    await svc.adjust_cash_balance(db, account, payload.balance)
    await db.refresh(account)
    return await _account_with_debt(db, space, account)


@router.get("/{account_id}/statements", response_model=list[StatementOut])
async def list_statements(
    db: DbSession, space_and_member: ActiveSpace, account_id: uuid.UUID
) -> list[StatementOut]:
    space, _ = space_and_member
    account = await svc.get_account(db, space.id, account_id)
    rows = (
        (
            await db.execute(
                select(Statement)
                .where(Statement.account_id == account.id)
                .order_by(Statement.period_end.desc())
            )
        )
        .scalars()
        .all()
    )
    today = today_in_tz(space.timezone)
    return [_statement_out(s, today) for s in rows]


@router.post(
    "/{account_id}/payments",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
)
async def pay_card(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    account_id: uuid.UUID,
    payload: PaymentCreate,
) -> TransactionOut:
    """TDC-10: registers the payment as a transfer into the credit account."""
    space, _ = space_and_member
    account = await svc.get_account(db, space.id, account_id)
    txn = await svc.register_payment(
        db,
        space,
        user.id,
        account,
        amount=payload.amount,
        from_account_id=payload.from_account_id,
        payment_date=payload.date,
        statement_id=payload.statement_id,
    )
    return await transaction_out(db, txn)


@router.post("/close-cycles", response_model=list[StatementOut])
async def close_cycles(db: DbSession, space_and_member: EditorSpace) -> list[StatementOut]:
    """Manual trigger of the daily close job (TDC-07) for the active space.
    Idempotent; also fires due reminders."""
    space, _ = space_and_member
    closed = await svc.close_due_statements(db, space)
    today = today_in_tz(space.timezone)
    await fire_due_reminders(db, today)
    return [_statement_out(s, today) for s in closed]


# El centro de notificaciones in-app vive en su propio router (REM-04..REM-07):
# ver app/api/v1/notifications.py.
