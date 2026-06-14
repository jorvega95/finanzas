"""Router: catalogs. Implements CAT-01..CAT-07; permissions per ESP-03."""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.catalogs import CardType, Category, CategoryKind, PaymentMethod
from app.schemas.catalogs import (
    CardTypeCreate,
    CardTypeOut,
    CardTypeUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    PaymentMethodCreate,
    PaymentMethodOut,
    PaymentMethodUpdate,
)
from app.services import catalogs as svc

router = APIRouter(prefix="/catalogs", tags=["catalogs"])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    db: DbSession,
    space_and_member: ActiveSpace,
    kind: CategoryKind | None = None,
    include_inactive: bool = False,
) -> list[Category]:
    """CAT-04: inactive entries are hidden from capture forms by default."""
    space, _ = space_and_member
    stmt = select(Category).where(Category.space_id == space.id, Category.is_system.is_(False))
    if kind is not None:
        stmt = stmt.where(Category.kind == kind)
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    rows = await db.execute(stmt.order_by(Category.name))
    return list(rows.scalars().all())


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: CategoryCreate
) -> Category:
    space, _ = space_and_member
    return await svc.create_category(
        db,
        space.id,
        user.id,
        name=payload.name,
        kind=payload.kind,
        expense_nature=payload.expense_nature,
        parent_id=payload.parent_id,
        icon=payload.icon,
        color=payload.color,
    )


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    db: DbSession,
    space_and_member: EditorSpace,
    category_id: uuid.UUID,
    payload: CategoryUpdate,
) -> Category:
    space, _ = space_and_member
    return await svc.update_category(
        db,
        space.id,
        category_id,
        name=payload.name,
        expense_nature=payload.expense_nature,
        icon=payload.icon,
        color=payload.color,
        is_active=payload.is_active,
    )


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    db: DbSession, space_and_member: EditorSpace, category_id: uuid.UUID
) -> None:
    space, _ = space_and_member
    await svc.delete_category(db, space.id, category_id)


@router.get("/payment-methods", response_model=list[PaymentMethodOut])
async def list_payment_methods(
    db: DbSession, space_and_member: ActiveSpace, include_inactive: bool = False
) -> list[PaymentMethod]:
    space, _ = space_and_member
    stmt = select(PaymentMethod).where(PaymentMethod.space_id == space.id)
    if not include_inactive:
        stmt = stmt.where(PaymentMethod.is_active.is_(True))
    rows = await db.execute(stmt.order_by(PaymentMethod.name))
    return list(rows.scalars().all())


@router.post(
    "/payment-methods", response_model=PaymentMethodOut, status_code=status.HTTP_201_CREATED
)
async def create_payment_method(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    payload: PaymentMethodCreate,
) -> PaymentMethod:
    space, _ = space_and_member
    return await svc.create_payment_method(
        db, space.id, user.id, name=payload.name, type=payload.type
    )


@router.patch("/payment-methods/{method_id}", response_model=PaymentMethodOut)
async def update_payment_method(
    db: DbSession,
    space_and_member: EditorSpace,
    method_id: uuid.UUID,
    payload: PaymentMethodUpdate,
) -> PaymentMethod:
    space, _ = space_and_member
    return await svc.update_payment_method(
        db, space.id, method_id, name=payload.name, is_active=payload.is_active
    )


@router.delete("/payment-methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_method(
    db: DbSession, space_and_member: EditorSpace, method_id: uuid.UUID
) -> None:
    space, _ = space_and_member
    await svc.delete_payment_method(db, space.id, method_id)


# --- Card types (CAT-08) -----------------------------------------------------


@router.get("/card-types", response_model=list[CardTypeOut])
async def list_card_types(
    db: DbSession, space_and_member: ActiveSpace, include_inactive: bool = False
) -> list[CardType]:
    space, _ = space_and_member
    stmt = select(CardType).where(CardType.space_id == space.id)
    if not include_inactive:
        stmt = stmt.where(CardType.is_active.is_(True))
    rows = await db.execute(stmt.order_by(CardType.name))
    return list(rows.scalars().all())


@router.post("/card-types", response_model=CardTypeOut, status_code=status.HTTP_201_CREATED)
async def create_card_type(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: CardTypeCreate
) -> CardType:
    space, _ = space_and_member
    return await svc.create_card_type(
        db,
        space.id,
        user.id,
        name=payload.name,
        behavior=payload.behavior,
        icon=payload.icon,
        color=payload.color,
    )


@router.patch("/card-types/{card_type_id}", response_model=CardTypeOut)
async def update_card_type(
    db: DbSession,
    space_and_member: EditorSpace,
    card_type_id: uuid.UUID,
    payload: CardTypeUpdate,
) -> CardType:
    space, _ = space_and_member
    return await svc.update_card_type(
        db,
        space.id,
        card_type_id,
        name=payload.name,
        icon=payload.icon,
        color=payload.color,
        is_active=payload.is_active,
    )


@router.delete("/card-types/{card_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card_type(
    db: DbSession, space_and_member: EditorSpace, card_type_id: uuid.UUID
) -> None:
    space, _ = space_and_member
    await svc.delete_card_type(db, space.id, card_type_id)
