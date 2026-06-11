"""Catalog services. Implements CAT-01..CAT-07.

Fase 0 ships the seed (CAT-02); CRUD arrives in Fase 1.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_name
from app.models.catalogs import (
    Category,
    CategoryKind,
    ExpenseNature,
    PaymentMethod,
    PaymentMethodType,
)

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
