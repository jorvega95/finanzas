"""Importación CSV. Implementa IMP-01..IMP-07.

Dedupe: sha256(space_id|date|amount|currency|descripcion_normalizada).
La preview nunca persiste nada (IMP-01); el confirm inserta lo seleccionado.
"""

import csv
import datetime as dt
import hashlib
import io
import json
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_name
from app.models.catalogs import Category, CategoryKind
from app.models.imports import ImportBatch, ImportStatus
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType

MAX_ROWS = 5000  # IMP-06
UNCATEGORIZED_NAME = "Sin categoría"  # IMP-03 (seed oculta, is_system)


def _normalize_description(description: str) -> str:
    """IMP-02: trim, lower, colapsar espacios."""
    return " ".join(description.strip().lower().split())


def dedupe_hash(
    space_id: uuid.UUID, date: dt.date, amount: Decimal, currency: str, description: str
) -> str:
    payload = (
        f"{space_id}|{date.isoformat()}|{amount}|{currency}|{_normalize_description(description)}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def parse_csv(
    content: str,
    *,
    date_column: str,
    amount_column: str,
    description_column: str | None,
    date_format: str = "%Y-%m-%d",
    decimal_separator: str = ".",
    delimiter: str = ",",
    negative_is_expense: bool = True,
    currency: str = "MXN",
) -> list[dict[str, Any]]:
    """IMP-01/IMP-06: parser puro de filas con validaciones por fila.

    Cada fila sale con type/date/amount/description o un `error` legible.
    """
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if reader.fieldnames is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "CSV vacío o sin encabezados")
    for required in (date_column, amount_column):
        if required not in reader.fieldnames:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Columna '{required}' no existe en el archivo",
            )

    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(reader):
        if len(rows) >= MAX_ROWS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Máximo {MAX_ROWS} filas por archivo (IMP-06)",
            )
        row: dict[str, Any] = {"row": index + 1, "error": None}
        description = (raw.get(description_column) or "") if description_column else ""
        row["description"] = description.strip()
        try:
            row["date"] = dt.datetime.strptime(
                (raw.get(date_column) or "").strip(), date_format
            ).date()
        except ValueError:
            row["error"] = f"Fecha inválida: {raw.get(date_column)!r}"
            rows.append(row)
            continue
        raw_amount = (raw.get(amount_column) or "").strip().replace(" ", "")
        if decimal_separator == ",":
            raw_amount = raw_amount.replace(".", "").replace(",", ".")
        else:
            raw_amount = raw_amount.replace(",", "")
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            row["error"] = f"Monto inválido: {raw.get(amount_column)!r}"
            rows.append(row)
            continue
        if amount == 0:
            row["error"] = "Monto cero"
            rows.append(row)
            continue
        if negative_is_expense:
            row["type"] = (
                TransactionType.expense.value if amount < 0 else TransactionType.income.value
            )
        else:
            row["type"] = TransactionType.expense.value
        row["amount"] = str(abs(amount))
        row["currency"] = currency
        rows.append(row)
    return rows


async def mark_duplicates(
    session: AsyncSession, space_id: uuid.UUID, rows: list[dict[str, Any]]
) -> None:
    """IMP-02: colisión contra transacciones existentes ⇒ 'posible duplicado'
    y des-seleccionada por default; el usuario decide."""
    for row in rows:
        row["is_duplicate"] = False
        row["selected"] = row["error"] is None
        if row["error"] is not None:
            row["selected"] = False
            continue
        candidates = (
            (
                await session.execute(
                    select(Transaction.description).where(
                        Transaction.space_id == space_id,
                        Transaction.date == row["date"],
                        Transaction.amount == Decimal(row["amount"]),
                        Transaction.currency == row["currency"],
                    )
                )
            )
            .scalars()
            .all()
        )
        normalized = _normalize_description(row["description"])
        if any(_normalize_description(c) == normalized for c in candidates):
            row["is_duplicate"] = True
            row["selected"] = False


async def _uncategorized_category(
    session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID
) -> Category:
    """IMP-03: seed oculta 'Sin categoría' (no aparece en formularios)."""
    normalized = normalize_name(UNCATEGORIZED_NAME)
    existing = await session.scalar(
        select(Category).where(
            Category.space_id == space_id,
            Category.kind == CategoryKind.expense,
            Category.name_normalized == normalized,
        )
    )
    if existing is not None:
        return existing
    category = Category(
        space_id=space_id,
        name=UNCATEGORIZED_NAME,
        name_normalized=normalized,
        kind=CategoryKind.expense,
        is_system=True,
        created_by=created_by,
    )
    session.add(category)
    await session.flush()
    return category


async def confirm_import(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    *,
    file_name: str,
    source: str,
    mapping: dict[str, Any],
    rows: list[dict[str, Any]],
    payment_method_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
) -> tuple[ImportBatch, int]:
    """IMP-01 paso final: inserta SOLO las filas seleccionadas en un batch.
    IMP-03: sin categoría inferible ⇒ 'Sin categoría' + bandeja de revisión.
    IMP-05: cargos TDC se asignan a su ciclo normalmente (TDC-05)."""
    from app.services.transactions import TransactionInput, create_transaction

    selected = [r for r in rows if r.get("selected") and not r.get("error")]
    if not selected:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No hay filas seleccionadas")
    if len(selected) > MAX_ROWS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Demasiadas filas (IMP-06)")

    income_fallback = None
    if category_id is None:
        uncategorized = await _uncategorized_category(session, space.id, created_by)
    batch = ImportBatch(
        space_id=space.id,
        source=source,
        file_name=file_name,
        row_count=len(selected),
        mapping=mapping,
        created_by=created_by,
    )
    session.add(batch)
    await session.flush()

    inserted = 0
    for row in selected:
        row_type = TransactionType(row["type"])
        row_category: uuid.UUID | None = category_id
        needs_review = False
        if row_category is None:
            if row_type == TransactionType.expense:
                row_category = uncategorized.id
            else:
                if income_fallback is None:
                    income_fallback = await session.scalar(
                        select(Category.id).where(
                            Category.space_id == space.id,
                            Category.kind == CategoryKind.income,
                            Category.is_active.is_(True),
                        )
                    )
                row_category = income_fallback
            needs_review = True  # IMP-03: bandeja de revisión (REC-03 reutilizada)
        date_value = row["date"]
        if isinstance(date_value, str):
            date_value = dt.date.fromisoformat(date_value)
        txn = await create_transaction(
            session,
            space,
            created_by,
            TransactionInput(
                type=row_type,
                date=date_value,
                amount=Decimal(row["amount"]),
                currency=row["currency"],
                description=row["description"],
                category_id=row_category,
                payment_method_id=payment_method_id,
            ),
            needs_review=needs_review,
        )
        txn.import_batch_id = batch.id
        inserted += 1
    await session.commit()
    await session.refresh(batch)
    return batch, inserted


async def rollback_batch(
    session: AsyncSession, space_id: uuid.UUID, batch_id: uuid.UUID
) -> dict[str, int]:
    """IMP-04: revierte el batch completo, excluyendo transacciones editadas
    manualmente (updated_by != NULL) e informándolo."""
    from app.services.transactions import delete_transaction

    batch = await session.get(ImportBatch, batch_id)
    if batch is None or batch.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch no encontrado")
    if batch.status != ImportStatus.confirmed:
        raise HTTPException(status.HTTP_409_CONFLICT, "El batch ya fue revertido")

    txns = (
        (await session.execute(select(Transaction).where(Transaction.import_batch_id == batch_id)))
        .scalars()
        .all()
    )
    removed = 0
    kept = 0
    for txn in txns:
        if txn.updated_by is not None:
            kept += 1  # editada a mano: se conserva (IMP-04)
            continue
        await delete_transaction(session, space_id, txn.id)
        removed += 1
    batch.status = ImportStatus.partially_rolled_back if kept else ImportStatus.rolled_back
    await session.commit()
    return {"removed": removed, "kept_edited": kept}


# --- Export (IMP-07) -------------------------------------------------------------


EXPORT_COLUMNS = [
    "date",
    "type",
    "amount",
    "currency",
    "description",
    "category",
    "payment_method",
    "notes",
]


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """CWE-1236: neutraliza fórmulas en celdas CSV.

    Excel/Sheets ejecutan el contenido de una celda que empieza con `=`, `+`,
    `-` o `@`. Los campos libres (description, notes) y los nombres de catálogo
    los escribe el usuario, así que se prefijan con `'` para forzar texto plano.
    """
    if value and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


async def export_transactions_csv(session: AsyncSession, space: Space) -> str:
    """IMP-07: CSV con el mismo esquema conceptual que el import."""
    from app.models.catalogs import PaymentMethod

    rows = (
        (
            await session.execute(
                select(Transaction)
                .where(Transaction.space_id == space.id)
                .order_by(Transaction.date)
            )
        )
        .scalars()
        .all()
    )
    categories = {
        c.id: c.name
        for c in (
            (await session.execute(select(Category).where(Category.space_id == space.id)))
            .scalars()
            .all()
        )
    }
    methods = {
        m.id: m.name
        for m in (
            (await session.execute(select(PaymentMethod).where(PaymentMethod.space_id == space.id)))
            .scalars()
            .all()
        )
    }
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPORT_COLUMNS)
    for txn in rows:
        writer.writerow(
            [
                txn.date.isoformat(),
                txn.type.value,
                str(txn.amount),
                txn.currency,
                _csv_safe(txn.description),
                _csv_safe(categories.get(txn.category_id, "")) if txn.category_id else "",
                _csv_safe(methods.get(txn.payment_method_id, "")) if txn.payment_method_id else "",
                _csv_safe(txn.notes or ""),
            ]
        )
    return output.getvalue()


async def export_full_json(session: AsyncSession, space: Space) -> str:
    """IMP-07: export JSON completo (mitigación de ESP-06)."""
    from app.models.cards import Card, CardStatement
    from app.models.catalogs import CardType, PaymentMethod
    from app.models.msi import InstallmentPlan

    def serialize(obj: Any) -> dict[str, Any]:
        return {
            column.name: (
                value.isoformat()
                if isinstance(value := getattr(obj, column.name), dt.date | dt.datetime)
                else str(value)
                if isinstance(value, Decimal | uuid.UUID)
                else value
            )
            for column in obj.__table__.columns
        }

    payload: dict[str, Any] = {"space": serialize(space)}
    for key, model in (
        ("categories", Category),
        ("card_types", CardType),
        ("payment_methods", PaymentMethod),
        ("transactions", Transaction),
        ("cards", Card),
        ("card_statements", CardStatement),
        ("installment_plans", InstallmentPlan),
    ):
        items = (
            (await session.execute(select(model).where(model.space_id == space.id))).scalars().all()
        )
        payload[key] = [serialize(item) for item in items]
    return json.dumps(payload, ensure_ascii=False, indent=2)
