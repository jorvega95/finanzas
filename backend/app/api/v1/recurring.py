"""Router: recurring rules. Implements REC-01..REC-05."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.recurring import RecurringRule
from app.schemas.recurring import RecurringRuleCreate, RecurringRuleOut, RecurringRuleUpdate
from app.services import recurring as svc
from app.services.transactions import SUPPORTED_CURRENCIES

router = APIRouter(prefix="/recurring-rules", tags=["recurring"])


@router.get("", response_model=list[RecurringRuleOut])
async def list_rules(
    db: DbSession, space_and_member: ActiveSpace, include_inactive: bool = False
) -> list[RecurringRule]:
    space, _ = space_and_member
    stmt = select(RecurringRule).where(RecurringRule.space_id == space.id)
    if not include_inactive:
        stmt = stmt.where(RecurringRule.is_active.is_(True))
    rows = await db.execute(stmt.order_by(RecurringRule.description))
    return list(rows.scalars().all())


@router.post("", response_model=RecurringRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: RecurringRuleCreate
) -> RecurringRule:
    space, _ = space_and_member
    if payload.currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Moneda no soportada: {payload.currency}"
        )
    month_day = svc.validate_rule_schedule(
        payload.frequency,
        payload.start_date,
        payload.month_day,
        payload.use_last_day,
        payload.type,
    )
    # Template references must belong to the space (GLO-05) and be active.
    if payload.category_id is not None:
        from app.services.transactions import _validate_category

        await _validate_category(db, space.id, payload.category_id, payload.type)
    if payload.payment_method_id is not None:
        from app.services.transactions import _validate_payment_method

        await _validate_payment_method(db, space.id, payload.payment_method_id)

    rule = RecurringRule(
        space_id=space.id,
        type=payload.type,
        amount=payload.amount,
        amount_is_estimate=payload.amount_is_estimate,
        currency=payload.currency,
        description=payload.description,
        category_id=payload.category_id,
        payment_method_id=payload.payment_method_id,
        frequency=payload.frequency,
        start_date=payload.start_date,
        end_date=payload.end_date,
        max_occurrences=payload.max_occurrences,
        month_day=month_day,
        use_last_day=payload.use_last_day,
        created_by=user.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RecurringRuleOut)
async def update_rule(
    db: DbSession, space_and_member: EditorSpace, rule_id: uuid.UUID, payload: RecurringRuleUpdate
) -> RecurringRule:
    """REC-04: edits affect only future instances; generated ones are kept."""
    space, _ = space_and_member
    rule = await svc.get_rule(db, space.id, rule_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    db: DbSession, space_and_member: EditorSpace, rule_id: uuid.UUID
) -> None:
    """Physically deletes a recurring rule. Confirmed transactions are kept
    with recurring_rule_id=NULL (FK SET NULL). Tombstones cascade-delete."""
    space, _ = space_and_member
    rule = await svc.get_rule(db, space.id, rule_id)
    await db.delete(rule)
    await db.commit()


@router.post("/generate", response_model=dict)
async def generate_now(db: DbSession, space_and_member: EditorSpace) -> dict[str, int]:
    """Manual trigger of the daily job for the active space (REC-02/05)."""
    space, _ = space_and_member
    created = await svc.generate_due_instances(db, space)
    return {"created": created}
