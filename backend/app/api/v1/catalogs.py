"""Router: catalogs. Implements CAT-01..CAT-08; permissions per ESP-03."""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.catalogs import AccountType, Category, CategoryKind
from app.schemas.catalogs import (
    AccountTypeCreate,
    AccountTypeOut,
    AccountTypeUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
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


# --- Account types (CAT-08) -----------------------------------------------------


@router.get("/account-types", response_model=list[AccountTypeOut])
async def list_account_types(
    db: DbSession, space_and_member: ActiveSpace, include_inactive: bool = False
) -> list[AccountType]:
    space, _ = space_and_member
    stmt = select(AccountType).where(AccountType.space_id == space.id)
    if not include_inactive:
        stmt = stmt.where(AccountType.is_active.is_(True))
    rows = await db.execute(stmt.order_by(AccountType.name))
    return list(rows.scalars().all())


@router.post("/account-types", response_model=AccountTypeOut, status_code=status.HTTP_201_CREATED)
async def create_account_type(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: AccountTypeCreate
) -> AccountType:
    space, _ = space_and_member
    return await svc.create_account_type(
        db,
        space.id,
        user.id,
        name=payload.name,
        behavior=payload.behavior,
        icon=payload.icon,
        color=payload.color,
    )


@router.patch("/account-types/{account_type_id}", response_model=AccountTypeOut)
async def update_account_type(
    db: DbSession,
    space_and_member: EditorSpace,
    account_type_id: uuid.UUID,
    payload: AccountTypeUpdate,
) -> AccountType:
    space, _ = space_and_member
    return await svc.update_account_type(
        db,
        space.id,
        account_type_id,
        name=payload.name,
        icon=payload.icon,
        color=payload.color,
        is_active=payload.is_active,
    )


@router.delete("/account-types/{account_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account_type(
    db: DbSession, space_and_member: EditorSpace, account_type_id: uuid.UUID
) -> None:
    space, _ = space_and_member
    await svc.delete_account_type(db, space.id, account_type_id)
