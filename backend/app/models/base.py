"""Shared model mixins. Implements GLO-04 (audit columns)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """created_at/updated_at are timestamptz (GLO-02: business dates stay `date`)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AuditMixin(TimestampMixin):
    """GLO-04: every domain entity carries created_by + timestamps."""

    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("profiles.id"), nullable=False)
