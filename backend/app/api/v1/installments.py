"""Router: MSI plans. Implements MSI-01..MSI-08."""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.cards import CreditCard
from app.models.transactions import Transaction
from app.schemas.cards import (
    InstallmentOut,
    PlanCreate,
    PlanOut,
    PlanSummaryOut,
    ProjectionRow,
)
from app.services import msi as svc

router = APIRouter(prefix="/installment-plans", tags=["installments"])


@router.post("", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: PlanCreate
) -> PlanOut:
    """MSI-01 (e IMP-05): convierte una compra TDC en plan MSI."""
    space, _ = space_and_member
    plan = await svc.create_plan_from_transaction(
        db, space, user.id, payload.transaction_id, payload.months
    )
    return PlanOut.model_validate(plan)


@router.get("", response_model=list[PlanSummaryOut])
async def list_plans(db: DbSession, space_and_member: ActiveSpace) -> list[PlanSummaryOut]:
    """MSI-06: vista por plan."""
    space, _ = space_and_member
    summaries = await svc.plans_summary(db, space.id)
    out: list[PlanSummaryOut] = []
    for item in summaries:
        plan = item["plan"]
        txn = await db.get(Transaction, plan.transaction_id)
        card = await db.get(CreditCard, plan.credit_card_id)
        out.append(
            PlanSummaryOut(
                plan=PlanOut.model_validate(plan),
                description=txn.description if txn else "",
                card_alias=card.alias if card else "",
                paid_count=item["paid_count"],
                charged_count=item["charged_count"],
                pending_count=item["pending_count"],
                remaining_amount=item["remaining_amount"],
                projected_payoff=item["projected_payoff"],
                installments=[InstallmentOut.model_validate(i) for i in plan.installments],
            )
        )
    return out


@router.get("/projection", response_model=list[ProjectionRow])
async def projection(db: DbSession, space_and_member: ActiveSpace) -> list[ProjectionRow]:
    """MSI-06 global: comprometido por mes futuro × tarjeta."""
    space, _ = space_and_member
    rows = await svc.monthly_projection(db, space.id)
    aliases = {
        c.id: c.alias
        for c in (await db.execute(select(CreditCard).where(CreditCard.space_id == space.id)))
        .scalars()
        .all()
    }
    return [
        ProjectionRow(
            credit_card_id=row["credit_card_id"],
            card_alias=aliases.get(row["credit_card_id"], ""),
            month=row["month"],
            amount=row["amount"],
        )
        for row in rows
    ]


@router.post("/{plan_id}/settle", response_model=PlanOut)
async def settle_plan(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, plan_id: uuid.UUID
) -> PlanOut:
    """MSI-07: liquidación anticipada."""
    space, _ = space_and_member
    plan = await svc.settle_plan_early(db, space, user.id, plan_id)
    return PlanOut.model_validate(plan)
