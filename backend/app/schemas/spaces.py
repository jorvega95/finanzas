"""Pydantic schemas for profiles and spaces (ESP-01..ESP-07)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.spaces import SpaceRole, SpaceType


class SpaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: SpaceType
    base_currency: str
    timezone: str
    role: SpaceRole


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str | None
    default_space_id: uuid.UUID | None
    locale: str


class MeOut(BaseModel):
    profile: ProfileOut
    spaces: list[SpaceOut]


class SpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_currency: str = Field(default="MXN", pattern="^[A-Z]{3}$")
    timezone: str = "America/Mexico_City"


class SpaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MemberOut(BaseModel):
    """ESP-03: miembro con su rol."""

    user_id: uuid.UUID
    display_name: str
    email: str | None
    role: SpaceRole


class MemberRoleUpdate(BaseModel):
    role: SpaceRole


class InviteCreate(BaseModel):
    """ESP-04."""

    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: SpaceRole = SpaceRole.editor


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: SpaceRole
    token: str  # el owner lo comparte; el email sale en Fase 6 (Resend)
    expires_at: datetime
    claimed_at: datetime | None


class InviteClaim(BaseModel):
    token: str = Field(min_length=10, max_length=64)


class SpaceDelete(BaseModel):
    """ESP-06: confirmación explícita con el nombre exacto."""

    confirm_name: str
