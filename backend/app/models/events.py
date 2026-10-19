"""Events. Implements EVT-01 (an event groups the movements of something
extraordinary — a wedding, a move, a trip — without changing categories)."""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import AuditMixin


class Event(Base, AuditMixin):
    """EVT-01: per-space event. Soft-delete (GLO-03): with linked movements it
    is only deactivated; an inactive event accepts no new links (CAT-04)."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("space_id", "name_normalized", name="uq_event_name"),
        CheckConstraint("budget IS NULL OR budget > 0", name="ck_event_budget_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(80), nullable=False)
    date: Mapped[dt.date | None] = mapped_column(Date)  # day of the event (optional)
    # Optional budget in the space's base currency (EVT-03).
    budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
