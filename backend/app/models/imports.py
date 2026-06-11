"""Import batches. Implements IMP-01..IMP-06."""

import enum
import uuid
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import AuditMixin


class ImportStatus(enum.StrEnum):
    confirmed = "confirmed"
    rolled_back = "rolled_back"
    partially_rolled_back = "partially_rolled_back"


class ImportBatch(Base, AuditMixin):
    """IMP-01: un batch por archivo confirmado (la preview nunca persiste)."""

    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="csv")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # IMP-01/IMP-06: column mapping + formats persisted for reuse per bank.
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", native_enum=False, length=25),
        nullable=False,
        default=ImportStatus.confirmed,
    )
