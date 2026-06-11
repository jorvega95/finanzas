"""Profiles, spaces and memberships. Implements ESP-01, ESP-02, ESP-03, GLO-05."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin


class SpaceType(enum.StrEnum):
    personal = "personal"
    shared = "shared"


class SpaceRole(enum.StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class Profile(Base, TimestampMixin):
    """Mirror of auth.users (Supabase). id == JWT `sub` (ESP-01)."""

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    # No FK to avoid profiles<->spaces circular dependency; always points to an
    # existing space (the personal space is the fallback, ESP-01).
    default_space_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="es-MX")

    memberships: Mapped[list["SpaceMember"]] = relationship(back_populates="profile")


class Space(Base, TimestampMixin):
    __tablename__ = "spaces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[SpaceType] = mapped_column(
        Enum(SpaceType, name="space_type", native_enum=False, length=10),
        nullable=False,
    )
    # FX-01: immutable once the first transaction exists (enforced in service).
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MXN")
    # GLO-02: "today" is resolved in the space timezone.
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="America/Mexico_City")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("profiles.id"), nullable=False)

    members: Mapped[list["SpaceMember"]] = relationship(
        back_populates="space", cascade="all, delete-orphan"
    )


class SpaceInvite(Base, TimestampMixin):
    """ESP-04: email-only invites, single-use token, 7-day expiry. A pending
    invite to the same email replaces the previous one."""

    __tablename__ = "space_invites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[SpaceRole] = mapped_column(
        Enum(SpaceRole, name="space_role", native_enum=False, length=10), nullable=False
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("profiles.id"), nullable=False)


class SpaceMember(Base):
    __tablename__ = "space_members"

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[SpaceRole] = mapped_column(
        Enum(SpaceRole, name="space_role", native_enum=False, length=10),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    space: Mapped[Space] = relationship(back_populates="members")
    profile: Mapped[Profile] = relationship(back_populates="memberships")
