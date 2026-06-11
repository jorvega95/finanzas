"""Router: budgets. Implements PRE-01..PRE-04."""

import uuid

from fastapi import APIRouter, status

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.schemas.dashboard import (
    BudgetCopy,
    BudgetCreate,
    BudgetOut,
    BudgetProgressOut,
    BudgetUpdate,
)
from app.services import budgets as svc

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("", response_model=list[BudgetProgressOut])
async def list_budgets(
    db: DbSession, space_and_member: ActiveSpace, month: str
) -> list[BudgetProgressOut]:
    """PRE-04: presupuesto vs consumido por categoría."""
    space, _ = space_and_member
    rows = await svc.budgets_with_progress(db, space, svc.parse_month(month))
    return [
        BudgetProgressOut(
            budget=BudgetOut.model_validate(row["budget"]),
            category_name=row["category_name"],
            consumed=row["consumed"],
            remaining=row["remaining"],
        )
        for row in rows
    ]


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
async def create_budget(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: BudgetCreate
) -> BudgetOut:
    space, _ = space_and_member
    budget = await svc.create_budget(
        db,
        space,
        user.id,
        category_id=payload.category_id,
        month=svc.parse_month(payload.month),
        amount=payload.amount,
        alert_threshold=payload.alert_threshold,
    )
    return BudgetOut.model_validate(budget)


@router.patch("/{budget_id}", response_model=BudgetOut)
async def update_budget(
    db: DbSession, space_and_member: EditorSpace, budget_id: uuid.UUID, payload: BudgetUpdate
) -> BudgetOut:
    space, _ = space_and_member
    budget = await svc.get_budget(db, space.id, budget_id)
    if payload.amount is not None:
        budget.amount = payload.amount
    if payload.alert_threshold is not None:
        budget.alert_threshold = payload.alert_threshold
    await db.commit()
    await db.refresh(budget)
    return BudgetOut.model_validate(budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(db: DbSession, space_and_member: EditorSpace, budget_id: uuid.UUID) -> None:
    space, _ = space_and_member
    budget = await svc.get_budget(db, space.id, budget_id)
    await db.delete(budget)
    await db.commit()


@router.post("/copy", response_model=dict)
async def copy_budgets(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: BudgetCopy
) -> dict[str, int]:
    """PRE-01: repetir presupuestos del mes anterior."""
    space, _ = space_and_member
    copied = await svc.copy_budgets(
        db, space, user.id, svc.parse_month(payload.from_month), svc.parse_month(payload.to_month)
    )
    return {"copied": copied}


@router.post("/check-alerts", response_model=dict)
async def check_alerts(db: DbSession, space_and_member: EditorSpace, month: str) -> dict[str, int]:
    """PRE-03: evalúa umbrales y crea alertas (idempotente)."""
    space, _ = space_and_member
    created = await svc.check_budget_alerts(db, space, svc.parse_month(month))
    return {"created": created}
