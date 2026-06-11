"""Reminders / notifications. Implements REM-01..REM-04."""

import datetime as dt
import enum
import uuid

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class ReminderKind(enum.StrEnum):
    card_due = "card_due"
    budget_alert = "budget_alert"
    custom = "custom"


class ReminderChannel(enum.StrEnum):
    in_app = "in_app"
    email = "email"


class ReminderStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    canceled = "canceled"
    failed = "failed"


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"
    __table_args__ = (
        # REM-02: one send per (statement, offset, channel).
        UniqueConstraint("kind", "ref_id", "offset_days", "channel", name="uq_reminder"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ReminderKind] = mapped_column(
        Enum(ReminderKind, name="reminder_kind", native_enum=False, length=15), nullable=False
    )
    ref_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fire_at: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    channel: Mapped[ReminderChannel] = mapped_column(
        Enum(ReminderChannel, name="reminder_channel", native_enum=False, length=10),
        nullable=False,
    )
    # REM-03: alias + amount + due date; never last4.
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus, name="reminder_status", native_enum=False, length=10),
        nullable=False,
        default=ReminderStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # REM-02 retries
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
