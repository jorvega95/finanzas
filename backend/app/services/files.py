"""File storage on local disk. Implements FAC-10.

Files live under `settings.files_path` as `{space}/{yyyy}/{mm}/{uuid}.{ext}`;
the DB keeps only metadata. The type is detected from the content (magic
bytes), never trusted from the name or the Content-Type, and the original
name never takes part in the path."""

import datetime as dt
import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.billing import StoredFile

MAX_FILE_BYTES = 15 * 1024 * 1024  # FAC-10
# FAC-10: detected type -> (extension, mime). Order matters only for xml.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"PK\x03\x04", "zip", "application/zip"),
    (b"%PDF-", "pdf", "application/pdf"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
)
# Types a browser may render in place; the rest are always downloaded.
INLINE_MIMES = {"application/pdf", "image/jpeg", "image/png"}


def detect_type(content: bytes) -> tuple[str, str] | None:
    """FAC-10: (extension, mime) from the first bytes, or None if not allowed."""
    for signature, ext, mime in _SIGNATURES:
        if content.startswith(signature):
            return ext, mime
    head = content[:64].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<?xml"):
        return "xml", "application/xml"
    return None


def _clean_name(name: str) -> str:
    """Keep only a display name: no directories, no control characters."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    return cleaned[:255] or "archivo"


def _write(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".partial")
    with open(tmp, "wb") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(target)


async def save_file(
    session: AsyncSession,
    space_id: uuid.UUID,
    created_by: uuid.UUID,
    content: bytes,
    original_name: str,
    today: dt.date,
) -> StoredFile:
    """FAC-10: validate, write to disk and record the metadata (flushed)."""
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El archivo está vacío")
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "El archivo excede el máximo de 15 MB"
        )
    detected = detect_type(content)
    if detected is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Tipo de archivo no permitido: sube un .zip, .pdf, .xml, .jpg o .png",
        )
    ext, mime = detected
    file_id = uuid.uuid4()
    relative = f"{space_id}/{today:%Y}/{today:%m}/{file_id}.{ext}"
    await run_in_threadpool(_write, settings.files_path / relative, content)
    stored = StoredFile(
        id=file_id,
        space_id=space_id,
        original_name=_clean_name(original_name),
        mime=mime,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_path=relative,
        created_by=created_by,
    )
    session.add(stored)
    await session.flush()
    return stored


async def get_file(session: AsyncSession, space_id: uuid.UUID, file_id: uuid.UUID) -> StoredFile:
    """GLO-05: a file of another space is 404."""
    stored: StoredFile | None = await session.scalar(
        select(StoredFile).where(StoredFile.id == file_id, StoredFile.space_id == space_id)
    )
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo no encontrado")
    return stored


def file_path(stored: StoredFile) -> Path:
    """Absolute path, refusing anything that escapes FILES_DIR."""
    root = settings.files_path.resolve()
    path = (root / stored.storage_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo no encontrado")
    return path
