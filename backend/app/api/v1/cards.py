"""Router: cards, statements and payments. Implements TDC-01..TDC-12, REM-04."""

import datetime as dt
import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.core.dates import today_in_tz
from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.cards import Card, CardStatement, StatementStatus
from app.models.catalogs import CardBehavior
from app.models.reminders import Reminder, ReminderChannel
from app.models.spaces import Space
from app.schemas.cards import (
    CardCreate,
    CardOut,
    CardUpdate,
    CardWithDebtOut,
    DebtSummary,
    NextPaymentOut,
    PaymentCreate,
    ReminderOut,
    StatementOut,
)
from app.schemas.transactions import TransactionOut
from app.services import cards as svc
from app.services.reminders import fire_due_reminders

router = APIRouter(prefix="/cards", tags=["cards"])


def _statement_out(statement: CardStatement, today: dt.date) -> StatementOut:
    out = StatementOut.model_validate(statement)
    # TDC-08: overdue is a flag computed against today, not a status.
    out.is_overdue = (
        statement.status in (StatementStatus.closed, StatementStatus.partially_paid)
        and today > statement.due_date
    )
    return out


async def _card_with_debt(db: DbSession, space: Space, card: Card) -> CardWithDebtOut:
    out = CardWithDebtOut.model_validate(card)
    out.behavior = await svc.card_behavior(db, card)
    if out.behavior == CardBehavior.credit:
        out.debt = DebtSummary(**(await svc.debt_summary(db, card)))  # TDC-09
        nxt = await svc.next_payment_due(db, card)  # TDC-14
        if nxt is not None:
            amount, due_date = nxt
            out.next_payment = NextPaymentOut(amount=amount, due_date=due_date)
        out.opening_balance = await svc.get_opening_balance(db, space, card)  # TDC-14
    else:
        out.balance = await svc.card_balance(db, card)  # TAR-05
    return out


@router.get("", response_model=list[CardWithDebtOut])
async def list_cards(
    db: DbSession, space_and_member: ActiveSpace, include_inactive: bool = False
) -> list[CardWithDebtOut]:
    space, _ = space_and_member
    stmt = select(Card).where(Card.space_id == space.id)
    if not include_inactive:
        stmt = stmt.where(Card.is_active.is_(True))
    cards = (await db.execute(stmt.order_by(Card.alias))).scalars().all()
    return [await _card_with_debt(db, space, card) for card in cards]


@router.post("", response_model=CardOut, status_code=status.HTTP_201_CREATED)
async def create_card(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: CardCreate
) -> Card:
    space, _ = space_and_member
    return await svc.create_card(
        db,
        space,
        user.id,
        card_type_id=payload.card_type_id,
        alias=payload.alias,
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
    )


@router.get("/{card_id}", response_model=CardWithDebtOut)
async def get_card(
    db: DbSession, space_and_member: ActiveSpace, card_id: uuid.UUID
) -> CardWithDebtOut:
    space, _ = space_and_member
    card = await svc.get_card(db, space.id, card_id)
    return await _card_with_debt(db, space, card)


@router.patch("/{card_id}", response_model=CardWithDebtOut)
async def update_card(
    db: DbSession,
    space_and_member: EditorSpace,
    card_id: uuid.UUID,
    payload: CardUpdate,
) -> CardWithDebtOut:
    """TDC-15: full edit; fields left blank at creation can be filled later."""
    space, _ = space_and_member
    card = await svc.get_card(db, space.id, card_id)
    changes = payload.model_dump(exclude_unset=True)
    is_active = changes.pop("is_active", None)
    if is_active is False:
        await svc.deactivate_card(db, card)  # TDC-12 (+ CAT-07 method)
    elif is_active is True:
        await svc.set_card_active(db, card, True)
    if changes:
        await svc.update_card(db, space, card, changes)
    await db.refresh(card)
    return await _card_with_debt(db, space, card)


@router.get("/{card_id}/statements", response_model=list[StatementOut])
async def list_statements(
    db: DbSession, space_and_member: ActiveSpace, card_id: uuid.UUID
) -> list[StatementOut]:
    space, _ = space_and_member
    card = await svc.get_card(db, space.id, card_id)
    rows = (
        (
            await db.execute(
                select(CardStatement)
                .where(CardStatement.credit_card_id == card.id)
                .order_by(CardStatement.period_end.desc())
            )
        )
        .scalars()
        .all()
    )
    today = today_in_tz(space.timezone)
    return [_statement_out(s, today) for s in rows]


@router.post(
    "/{card_id}/payments",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
)
async def pay_card(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    card_id: uuid.UUID,
    payload: PaymentCreate,
) -> TransactionOut:
    """TDC-10: registers the payment as a transfer into the card's method."""
    space, _ = space_and_member
    card = await svc.get_card(db, space.id, card_id)
    txn = await svc.register_payment(
        db,
        space,
        user.id,
        card,
        amount=payload.amount,
        from_payment_method_id=payload.from_payment_method_id,
        payment_date=payload.date,
        statement_id=payload.statement_id,
    )
    return TransactionOut.model_validate(txn)


@router.post("/close-cycles", response_model=list[StatementOut])
async def close_cycles(db: DbSession, space_and_member: EditorSpace) -> list[StatementOut]:
    """Manual trigger of the daily close job (TDC-07) for the active space.
    Idempotent; also fires due reminders."""
    space, _ = space_and_member
    closed = await svc.close_due_statements(db, space)
    today = today_in_tz(space.timezone)
    await fire_due_reminders(db, today)
    return [_statement_out(s, today) for s in closed]


@router.get("/notifications/inbox", response_model=list[ReminderOut])
async def notifications_inbox(db: DbSession, space_and_member: ActiveSpace) -> list[Reminder]:
    """REM-04: in-app notification center."""
    space, _ = space_and_member
    rows = await db.execute(
        select(Reminder)
        .where(
            Reminder.space_id == space.id,
            Reminder.channel == ReminderChannel.in_app,
        )
        .order_by(Reminder.fire_at.desc())
        .limit(50)
    )
    return list(rows.scalars().all())
