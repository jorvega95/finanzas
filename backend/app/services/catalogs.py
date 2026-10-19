"""Catalog services. Implements CAT-01..CAT-08, GLO-03."""

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_name
from app.models.accounts import Account
from app.models.catalogs import (
    AccountBehavior,
    AccountType,
    Category,
    CategoryKind,
    ExpenseNature,
)
from app.models.transactions import Transaction

# CAT-02 + CAT-03: default expense categories with their nature. All editable.
SEED_EXPENSE_CATEGORIES: list[tuple[str, ExpenseNature]] = [
    ("Comida", ExpenseNature.variable),
    ("Súper", ExpenseNature.variable),
    ("Transporte", ExpenseNature.variable),
    ("Vivienda", ExpenseNature.fixed),
    ("Servicios", ExpenseNature.fixed),
    ("Salud", ExpenseNature.variable),
    ("Entretenimiento", ExpenseNature.discretionary),
    ("Ropa", ExpenseNature.discretionary),
    ("Educación", ExpenseNature.fixed),
    ("Regalos", ExpenseNature.discretionary),
    ("Otros", ExpenseNature.variable),
]
SEED_INCOME_CATEGORIES: list[str] = ["Nómina", "Freelance", "Intereses", "Otros"]
# CAT-08: default account types. Name is free/editable; behavior is fixed.
SEED_ACCOUNT_TYPES: list[tuple[str, AccountBehavior]] = [
    ("Crédito", AccountBehavior.credit),
    ("Débito", AccountBehavior.debit),
    ("Billetera digital", AccountBehavior.debit),
    ("Vales de despensa", AccountBehavior.prepaid),
    ("Tarjeta de regalo", AccountBehavior.prepaid),
    ("Efectivo", AccountBehavior.cash),
    ("Ahorro", AccountBehavior.savings),
]
CASH_ACCOUNT_NAME = "Efectivo"  # CAT-02: seeded cash account (TAR-09).


def seed_catalogs(
    session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID, currency: str = "MXN"
) -> None:
    """CAT-02: seed default categories, account types and the cash account."""
    for name, nature in SEED_EXPENSE_CATEGORIES:
        session.add(
            Category(
                space_id=space_id,
                name=name,
                name_normalized=normalize_name(name),
                kind=CategoryKind.expense,
                expense_nature=nature,
                created_by=created_by,
            )
        )
    for name in SEED_INCOME_CATEGORIES:
        session.add(
            Category(
                space_id=space_id,
                name=name,
                name_normalized=normalize_name(name),
                kind=CategoryKind.income,
                created_by=created_by,
            )
        )
    for name, behavior in SEED_ACCOUNT_TYPES:
        account_type = AccountType(
            space_id=space_id,
            name=name,
            name_normalized=normalize_name(name),
            behavior=behavior,
            is_system=True,
            created_by=created_by,
        )
        session.add(account_type)
        if behavior == AccountBehavior.cash:
            session.add(
                Account(
                    space_id=space_id,
                    account_type=account_type,
                    name=CASH_ACCOUNT_NAME,
                    name_normalized=normalize_name(CASH_ACCOUNT_NAME),
                    currency=currency,
                    initial_balance=Decimal("0.00"),
                    allow_overdraft=True,  # TAR-09
                    reminder_days=[],
                    created_by=created_by,
                )
            )


# --- CRUD (Fase 1) -----------------------------------------------------------


async def _ensure_unique_category(
    session: AsyncSession,
    space_id: uuid.UUID,
    kind: CategoryKind,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """CAT-01: name unique per space + kind, case/accent-insensitive."""
    normalized = normalize_name(name)
    stmt = select(Category.id).where(
        Category.space_id == space_id,
        Category.kind == kind,
        Category.name_normalized == normalized,
    )
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una categoría con ese nombre")
    return normalized


async def get_category(
    session: AsyncSession, space_id: uuid.UUID, category_id: uuid.UUID
) -> Category:
    category = await session.get(Category, category_id)
    if category is None or category.space_id != space_id:
        # GLO-05: cross-space access is indistinguishable from not-found.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoría no encontrada")
    return category


async def create_category(
    session: AsyncSession,
    space_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    name: str,
    kind: CategoryKind,
    expense_nature: ExpenseNature | None = None,
    parent_id: uuid.UUID | None = None,
    icon: str | None = None,
    color: str | None = None,
) -> Category:
    parent: Category | None = None
    if parent_id is not None:
        parent = await get_category(session, space_id, parent_id)
        # CAT-06: max 2 levels; a subcategory inherits kind from its parent.
        if parent.parent_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Máximo 2 niveles: una subcategoría no puede tener hijas",
            )
        kind = parent.kind
        # CAT-06: inherits expense_nature unless overridden.
        if expense_nature is None:
            expense_nature = parent.expense_nature

    if kind == CategoryKind.income:
        expense_nature = None  # CAT-03: nature applies to expenses only.
    elif expense_nature is None and parent is None:
        expense_nature = ExpenseNature.variable

    normalized = await _ensure_unique_category(session, space_id, kind, name)
    category = Category(
        space_id=space_id,
        name=name,
        name_normalized=normalized,
        kind=kind,
        expense_nature=expense_nature,
        parent_id=parent_id,
        icon=icon,
        color=color,
        created_by=created_by,
    )
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


async def update_category(
    session: AsyncSession,
    space_id: uuid.UUID,
    category_id: uuid.UUID,
    *,
    name: str | None = None,
    expense_nature: ExpenseNature | None = None,
    icon: str | None = None,
    color: str | None = None,
    is_active: bool | None = None,
) -> Category:
    category = await get_category(session, space_id, category_id)

    if name is not None and name != category.name:
        category.name_normalized = await _ensure_unique_category(
            session, space_id, category.kind, name, exclude_id=category.id
        )
        category.name = name
    if expense_nature is not None and category.kind == CategoryKind.expense:
        category.expense_nature = expense_nature
    if icon is not None:
        category.icon = icon
    if color is not None:
        category.color = color

    if is_active is not None and is_active != category.is_active:
        if not is_active:
            # CAT-05: never deactivate the last active category of a kind.
            active_count = await session.scalar(
                select(func.count())
                .select_from(Category)
                .where(
                    Category.space_id == space_id,
                    Category.kind == category.kind,
                    Category.is_active.is_(True),
                    Category.is_system.is_(False),
                )
            )
            if (active_count or 0) <= 1:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "No puedes desactivar la última categoría activa",
                )
        category.is_active = is_active  # CAT-04: reactivation always allowed.

    await session.commit()
    await session.refresh(category)
    return category


async def delete_category(
    session: AsyncSession, space_id: uuid.UUID, category_id: uuid.UUID
) -> None:
    """GLO-03: physical delete only without references; otherwise deactivate."""
    category = await get_category(session, space_id, category_id)
    has_txns = await session.scalar(select(exists().where(Transaction.category_id == category_id)))
    has_children = await session.scalar(select(exists().where(Category.parent_id == category_id)))
    if has_txns or has_children:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "La categoría tiene registros asociados; desactívala en su lugar",
        )
    await session.delete(category)
    await session.commit()


# --- Account types (CAT-08) --------------------------------------------------


async def _ensure_unique_account_type(
    session: AsyncSession,
    space_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """CAT-08: name unique per space, case/accent-insensitive."""
    normalized = normalize_name(name)
    stmt = select(AccountType.id).where(
        AccountType.space_id == space_id,
        AccountType.name_normalized == normalized,
    )
    if exclude_id is not None:
        stmt = stmt.where(AccountType.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un tipo de cuenta con ese nombre")
    return normalized


async def get_account_type(
    session: AsyncSession, space_id: uuid.UUID, account_type_id: uuid.UUID
) -> AccountType:
    account_type = await session.get(AccountType, account_type_id)
    if account_type is None or account_type.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tipo de cuenta no encontrado")
    return account_type


async def create_account_type(
    session: AsyncSession,
    space_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    name: str,
    behavior: AccountBehavior,
    icon: str | None = None,
    color: str | None = None,
) -> AccountType:
    normalized = await _ensure_unique_account_type(session, space_id, name)
    account_type = AccountType(
        space_id=space_id,
        name=name,
        name_normalized=normalized,
        behavior=behavior,
        icon=icon,
        color=color,
        created_by=created_by,
    )
    session.add(account_type)
    await session.commit()
    await session.refresh(account_type)
    return account_type


async def _account_type_in_use(session: AsyncSession, account_type_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(select(exists().where(Account.account_type_id == account_type_id)))
    )


async def update_account_type(
    session: AsyncSession,
    space_id: uuid.UUID,
    account_type_id: uuid.UUID,
    *,
    name: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    is_active: bool | None = None,
) -> AccountType:
    """CAT-08: behavior is immutable (system classifier). A type with accounts
    cannot be deactivated."""
    account_type = await get_account_type(session, space_id, account_type_id)

    if name is not None and name != account_type.name:
        account_type.name_normalized = await _ensure_unique_account_type(
            session, space_id, name, exclude_id=account_type.id
        )
        account_type.name = name
    if icon is not None:
        account_type.icon = icon
    if color is not None:
        account_type.color = color
    if is_active is not None and is_active != account_type.is_active:
        if not is_active and await _account_type_in_use(session, account_type.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "El tipo tiene cuentas asociadas; no puede desactivarse",
            )
        account_type.is_active = is_active

    await session.commit()
    await session.refresh(account_type)
    return account_type


async def delete_account_type(
    session: AsyncSession, space_id: uuid.UUID, account_type_id: uuid.UUID
) -> None:
    """CAT-08/GLO-03: physical delete only without accounts referencing it."""
    account_type = await get_account_type(session, space_id, account_type_id)
    if await _account_type_in_use(session, account_type.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El tipo tiene cuentas asociadas; desactívalo en su lugar",
        )
    await session.delete(account_type)
    await session.commit()
