"""Catalog services. Implements CAT-01..CAT-07, GLO-03."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_name
from app.models.catalogs import (
    Category,
    CategoryKind,
    ExpenseNature,
    PaymentMethod,
    PaymentMethodType,
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
SEED_PAYMENT_METHODS: list[tuple[str, PaymentMethodType]] = [
    ("Efectivo", PaymentMethodType.cash),
    ("Débito", PaymentMethodType.debit),
    ("Transferencia", PaymentMethodType.transfer),
]


def seed_catalogs(session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID) -> None:
    """CAT-02: seed default categories and payment methods for a new space."""
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
    for name, method_type in SEED_PAYMENT_METHODS:
        session.add(
            PaymentMethod(
                space_id=space_id,
                name=name,
                name_normalized=normalize_name(name),
                type=method_type,
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


async def _ensure_unique_payment_method(
    session: AsyncSession,
    space_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    normalized = normalize_name(name)
    stmt = select(PaymentMethod.id).where(
        PaymentMethod.space_id == space_id,
        PaymentMethod.name_normalized == normalized,
    )
    if exclude_id is not None:
        stmt = stmt.where(PaymentMethod.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un método de pago con ese nombre")
    return normalized


async def get_payment_method(
    session: AsyncSession, space_id: uuid.UUID, method_id: uuid.UUID
) -> PaymentMethod:
    method = await session.get(PaymentMethod, method_id)
    if method is None or method.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Método de pago no encontrado")
    return method


async def create_payment_method(
    session: AsyncSession,
    space_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    name: str,
    type: PaymentMethodType,
    credit_card_id: uuid.UUID | None = None,
) -> PaymentMethod:
    # CAT-07: a credit_card method must reference a card; those are created
    # automatically with the card (TDC-01), never by hand.
    if type == PaymentMethodType.credit_card and credit_card_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Un método de tarjeta de crédito se crea junto con la tarjeta",
        )
    normalized = await _ensure_unique_payment_method(session, space_id, name)
    method = PaymentMethod(
        space_id=space_id,
        name=name,
        name_normalized=normalized,
        type=type,
        credit_card_id=credit_card_id,
        created_by=created_by,
    )
    session.add(method)
    await session.commit()
    await session.refresh(method)
    return method


async def update_payment_method(
    session: AsyncSession,
    space_id: uuid.UUID,
    method_id: uuid.UUID,
    *,
    name: str | None = None,
    is_active: bool | None = None,
) -> PaymentMethod:
    method = await get_payment_method(session, space_id, method_id)

    if name is not None and name != method.name:
        method.name_normalized = await _ensure_unique_payment_method(
            session, space_id, name, exclude_id=method.id
        )
        method.name = name

    if is_active is not None and is_active != method.is_active:
        if not is_active:
            # CAT-05: never deactivate the last active payment method.
            active_count = await session.scalar(
                select(func.count())
                .select_from(PaymentMethod)
                .where(
                    PaymentMethod.space_id == space_id,
                    PaymentMethod.is_active.is_(True),
                )
            )
            if (active_count or 0) <= 1:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "No puedes desactivar el último método de pago activo",
                )
        method.is_active = is_active

    await session.commit()
    await session.refresh(method)
    return method


async def delete_payment_method(
    session: AsyncSession, space_id: uuid.UUID, method_id: uuid.UUID
) -> None:
    """GLO-03: physical delete only without references."""
    method = await get_payment_method(session, space_id, method_id)
    has_txns = await session.scalar(
        select(
            exists().where(
                (Transaction.payment_method_id == method_id)
                | (Transaction.payment_method_to_id == method_id)
            )
        )
    )
    if has_txns:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El método tiene transacciones asociadas; desactívalo en su lugar",
        )
    await session.delete(method)
    await session.commit()
