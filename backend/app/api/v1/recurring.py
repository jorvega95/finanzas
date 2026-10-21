"""Router: recurring rules and subscriptions. Implements REC-01..REC-13."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.accounts import Account
from app.models.recurring import RecurringKind, RecurringRule
from app.models.spaces import Space
from app.models.transactions import Transaction
from app.schemas.recurring import (
    BillCapture,
    BillSkip,
    PendingBillOut,
    RecurringRuleCreate,
    RecurringRuleOut,
    RecurringRuleUpdate,
    SubscriptionSummaryOut,
)
from app.schemas.transactions import TransactionOut
from app.services import fx
from app.services import recurring as svc
from app.services.transactions import SUPPORTED_CURRENCIES, _validate_category, validate_account

router = APIRouter(prefix="/recurring-rules", tags=["recurring"])


async def _out(db: AsyncSession, rule: RecurringRule, space: Space) -> RecurringRuleOut:
    today = today_in_tz(space.timezone)
    out = RecurringRuleOut.model_validate(rule)
    out.status = svc.rule_status(rule, today)  # type: ignore[assignment]
    out.next_date = svc.next_occurrence(rule, today) if out.status != "canceled" else None
    account = await db.get(Account, rule.account_id)
    if account is not None:
        out.account_currency = account.currency
        if rule.amount is not None and rule.currency != account.currency:
            out.account_amount_today = await fx.convert(
                db, rule.amount, rule.currency, account.currency, today
            )
    return out


def _check_currency(currency: str) -> None:
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Moneda no soportada: {currency}"
        )


@router.get("", response_model=list[RecurringRuleOut])
async def list_rules(
    db: DbSession,
    space_and_member: ActiveSpace,
    include_inactive: bool = False,
    kind: RecurringKind | None = None,
) -> list[RecurringRuleOut]:
    space, _ = space_and_member
    stmt = select(RecurringRule).where(RecurringRule.space_id == space.id)
    if not include_inactive:
        stmt = stmt.where(RecurringRule.is_active.is_(True))
    if kind is not None:
        stmt = stmt.where(RecurringRule.kind == kind)
    rows = await db.execute(stmt.order_by(RecurringRule.description))
    return [await _out(db, rule, space) for rule in rows.scalars().all()]


@router.get("/pending-bills", response_model=list[PendingBillOut])
async def list_pending_bills(db: DbSession, space_and_member: ActiveSpace) -> list[PendingBillOut]:
    """REC-11: bandeja "Por capturar"."""
    space, _ = space_and_member
    return [
        PendingBillOut(
            rule_id=item.rule.id,
            description=item.rule.description,
            scheduled_date=item.scheduled_date,
            estimate=item.rule.amount,
            currency=item.rule.currency,
            account_id=item.rule.account_id,
            category_id=item.rule.category_id,
        )
        for item in await svc.pending_bills(db, space)
    ]


@router.get("/summary", response_model=SubscriptionSummaryOut)
async def subscriptions_summary(
    db: DbSession, space_and_member: ActiveSpace
) -> svc.SubscriptionSummary:
    """REC-13: costo mensual equivalente de las suscripciones."""
    space, _ = space_and_member
    return await svc.subscription_summary(db, space)


@router.post("", response_model=RecurringRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: RecurringRuleCreate
) -> RecurringRuleOut:
    space, _ = space_and_member
    _check_currency(payload.currency)
    month_day = svc.validate_rule_schedule(
        payload.frequency,
        payload.start_date,
        payload.month_day,
        payload.use_last_day,
        payload.type,
    )
    # Template references must belong to the space (GLO-05) and be active.
    if payload.category_id is not None:
        await _validate_category(db, space.id, payload.category_id, payload.type)
    account = await validate_account(db, space.id, payload.account_id)
    svc.validate_rule_shape(
        kind=payload.kind,
        type=payload.type,
        amount=payload.amount,
        currency=payload.currency,
        account=account,
        is_trial=payload.is_trial,
    )

    rule = RecurringRule(
        space_id=space.id,
        kind=payload.kind,
        type=payload.type,
        amount=payload.amount,
        amount_is_estimate=payload.amount_is_estimate,
        currency=payload.currency,
        description=payload.description,
        category_id=payload.category_id,
        account_id=payload.account_id,
        frequency=payload.frequency,
        start_date=payload.start_date,
        end_date=payload.end_date,
        max_occurrences=payload.max_occurrences,
        month_day=month_day,
        use_last_day=payload.use_last_day,
        is_trial=payload.is_trial,
        reminder_days=(
            payload.reminder_days
            if payload.reminder_days is not None
            else svc.DEFAULT_REMINDER_DAYS[payload.kind]
        ),
        cancel_url=payload.cancel_url,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(rule)
    await db.flush()
    await svc.sync_reminders(db, space, [rule.id])  # REC-12
    await db.commit()
    await db.refresh(rule)
    return await _out(db, rule, space)


@router.patch("/{rule_id}", response_model=RecurringRuleOut)
async def update_rule(
    db: DbSession, space_and_member: EditorSpace, rule_id: uuid.UUID, payload: RecurringRuleUpdate
) -> RecurringRuleOut:
    """REC-04: edits affect only future instances; generated ones are kept."""
    space, _ = space_and_member
    rule = await svc.get_rule(db, space.id, rule_id)
    data = payload.model_dump(exclude_unset=True)
    # GLO-05: las referencias editables deben seguir perteneciendo al espacio
    # activo (create_rule ya lo valida; el update no debe ser una puerta trasera).
    if data.get("category_id") is not None:
        await _validate_category(db, space.id, data["category_id"], rule.type)
    for required in ("account_id", "currency", "description"):
        if required in data and data[required] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{required} es obligatorio")
    if "currency" in data:
        _check_currency(data["currency"])
    if data.keys() & {"account_id", "currency", "amount"}:
        account = await validate_account(db, space.id, data.get("account_id", rule.account_id))
        svc.validate_rule_shape(
            kind=rule.kind,
            type=rule.type,
            amount=data["amount"] if "amount" in data else rule.amount,
            currency=data.get("currency", rule.currency),
            account=account,
            is_trial=rule.is_trial,
        )
    if data.get("is_active") is True:
        data["canceled_at"] = None  # REC-09: resuming a canceled rule reactivates it

    for field, value in data.items():
        setattr(rule, field, value)
    await db.flush()
    await svc.sync_reminders(db, space, [rule.id])  # REC-12
    await db.commit()
    await db.refresh(rule)
    return await _out(db, rule, space)


@router.post("/{rule_id}/cancel", response_model=RecurringRuleOut)
async def cancel_rule(
    db: DbSession, space_and_member: EditorSpace, rule_id: uuid.UUID
) -> RecurringRuleOut:
    """REC-09: cancel keeping history; cancels its reminders."""
    space, _ = space_and_member
    rule = await svc.get_rule(db, space.id, rule_id)
    await svc.cancel_rule(db, space, rule)
    await db.refresh(rule)
    return await _out(db, rule, space)


@router.post("/{rule_id}/reactivate", response_model=RecurringRuleOut)
async def reactivate_rule(
    db: DbSession, space_and_member: EditorSpace, rule_id: uuid.UUID
) -> RecurringRuleOut:
    """REC-09: undo a cancellation (or a pause)."""
    space, _ = space_and_member
    rule = await svc.get_rule(db, space.id, rule_id)
    await svc.reactivate_rule(db, space, rule)
    await db.refresh(rule)
    return await _out(db, rule, space)


@router.post(
    "/{rule_id}/capture", response_model=TransactionOut, status_code=status.HTTP_201_CREATED
)
async def capture_bill(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    rule_id: uuid.UUID,
    payload: BillCapture,
) -> Transaction:
    """REC-11: registrar el monto real de un recibo."""
    space, _ = space_and_member
    return await svc.capture_bill(
        db, space, user.id, rule_id, payload.scheduled_date, payload.amount, payload.date
    )


@router.post("/{rule_id}/skip", status_code=status.HTTP_204_NO_CONTENT)
async def skip_bill(
    db: DbSession, space_and_member: EditorSpace, rule_id: uuid.UUID, payload: BillSkip
) -> None:
    """REC-11: omitir un recibo (tombstone)."""
    space, _ = space_and_member
    await svc.skip_bill(db, space, rule_id, payload.scheduled_date)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(db: DbSession, space_and_member: EditorSpace, rule_id: uuid.UUID) -> None:
    """Physically deletes a recurring rule. Confirmed transactions are kept
    with recurring_rule_id=NULL (FK SET NULL). Tombstones and reminders
    cascade-delete (REC-12)."""
    space, _ = space_and_member
    rule = await svc.get_rule(db, space.id, rule_id)
    await db.delete(rule)
    await db.commit()


@router.post("/generate", response_model=dict)
async def generate_now(db: DbSession, space_and_member: EditorSpace) -> dict[str, int]:
    """Manual trigger of the daily job for the active space (REC-02/05)."""
    space, _ = space_and_member
    created = await svc.generate_due_instances(db, space)
    await svc.sync_reminders(db, space)
    await db.commit()
    return {"created": created}
