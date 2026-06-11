"""Router: CSV import wizard + export. Implements IMP-01..IMP-07."""

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.imports import ImportBatch, ImportStatus
from app.services import imports as svc

router = APIRouter(tags=["imports"])


class MappingConfig(BaseModel):
    """IMP-01/IMP-06: mapeo de columnas y formatos por plantilla de banco."""

    date_column: str
    amount_column: str
    description_column: str | None = None
    date_format: str = "%Y-%m-%d"
    decimal_separator: str = Field(default=".", pattern="^[.,]$")
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    negative_is_expense: bool = True
    currency: str = Field(default="MXN", pattern="^[A-Z]{3}$")


class PreviewRequest(BaseModel):
    content: str
    mapping: MappingConfig


class PreviewRow(BaseModel):
    row: int
    date: dt.date | None = None
    type: str | None = None
    amount: str | None = None
    currency: str | None = None
    description: str = ""
    error: str | None = None
    is_duplicate: bool = False
    selected: bool = False


class PreviewResponse(BaseModel):
    rows: list[PreviewRow]
    total: int
    duplicates: int
    invalid: int


class ConfirmRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    source: str = Field(default="csv", max_length=60)
    mapping: MappingConfig
    rows: list[PreviewRow]
    payment_method_id: uuid.UUID
    category_id: uuid.UUID | None = None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    file_name: str
    row_count: int
    status: ImportStatus


@router.post("/imports/preview", response_model=PreviewResponse)
async def preview(
    db: DbSession, space_and_member: EditorSpace, payload: PreviewRequest
) -> PreviewResponse:
    """IMP-01: parsea y valida SIN insertar; IMP-02 marca duplicados."""
    space, _ = space_and_member
    rows = svc.parse_csv(payload.content, **payload.mapping.model_dump())
    await svc.mark_duplicates(db, space.id, rows)
    return PreviewResponse(
        rows=[PreviewRow(**row) for row in rows],
        total=len(rows),
        duplicates=sum(1 for r in rows if r["is_duplicate"]),
        invalid=sum(1 for r in rows if r["error"]),
    )


@router.post("/imports/confirm", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def confirm(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: ConfirmRequest
) -> BatchOut:
    space, _ = space_and_member
    batch, _inserted = await svc.confirm_import(
        db,
        space,
        user.id,
        file_name=payload.file_name,
        source=payload.source,
        mapping=payload.mapping.model_dump(),
        rows=[row.model_dump() for row in payload.rows],
        payment_method_id=payload.payment_method_id,
        category_id=payload.category_id,
    )
    return BatchOut.model_validate(batch)


@router.get("/imports", response_model=list[BatchOut])
async def list_batches(db: DbSession, space_and_member: ActiveSpace) -> list[ImportBatch]:
    space, _ = space_and_member
    rows = await db.execute(
        select(ImportBatch)
        .where(ImportBatch.space_id == space.id)
        .order_by(ImportBatch.created_at.desc())
    )
    return list(rows.scalars().all())


@router.post("/imports/{batch_id}/rollback", response_model=dict)
async def rollback(
    db: DbSession, space_and_member: EditorSpace, batch_id: uuid.UUID
) -> dict[str, Any]:
    """IMP-04: revierte el batch; las editadas a mano se conservan."""
    space, _ = space_and_member
    return await svc.rollback_batch(db, space.id, batch_id)


@router.get("/exports/transactions.csv")
async def export_csv(db: DbSession, space_and_member: ActiveSpace) -> Response:
    """IMP-07."""
    space, _ = space_and_member
    content = await svc.export_transactions_csv(db, space)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
    )


@router.get("/exports/full.json")
async def export_json(db: DbSession, space_and_member: ActiveSpace) -> Response:
    """IMP-07: export completo (mitigación ESP-06)."""
    space, _ = space_and_member
    content = await svc.export_full_json(db, space)
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="finanzas.json"'},
    )
