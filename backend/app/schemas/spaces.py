"""Pydantic schemas for profiles and spaces (ESP-01..ESP-03)."""

import uuid

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
