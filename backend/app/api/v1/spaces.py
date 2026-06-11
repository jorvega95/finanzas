"""Router: profile bootstrap and spaces. Implements ESP-01..ESP-03, GLO-05."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.spaces import Profile, Space, SpaceMember, SpaceRole
from app.schemas.spaces import MeOut, ProfileOut, SpaceCreate, SpaceOut, SpaceUpdate
from app.services.spaces import create_shared_space, list_user_spaces

router = APIRouter(tags=["spaces"])


def _space_out(space: Space, member: SpaceMember) -> SpaceOut:
    return SpaceOut(
        id=space.id,
        name=space.name,
        type=space.type,
        base_currency=space.base_currency,
        timezone=space.timezone,
        role=member.role,
    )


async def _get_membership(
    db: DbSession, user: Profile, space_id: uuid.UUID
) -> tuple[Space, SpaceMember]:
    """GLO-05: non-members get 404 — existence is never leaked."""
    row = (
        await db.execute(
            select(Space, SpaceMember)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(Space.id == space_id, SpaceMember.user_id == user.id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    return row[0], row[1]


@router.get("/me", response_model=MeOut)
async def get_me(db: DbSession, user: CurrentUser) -> MeOut:
    """Session bootstrap. First call provisions profile + personal space (ESP-01)."""
    spaces = await list_user_spaces(db, user.id)
    return MeOut(
        profile=ProfileOut.model_validate(user),
        spaces=[_space_out(s, m) for s, m in spaces],
    )


@router.get("/spaces", response_model=list[SpaceOut])
async def get_spaces(db: DbSession, user: CurrentUser) -> list[SpaceOut]:
    return [_space_out(s, m) for s, m in await list_user_spaces(db, user.id)]


@router.post("/spaces", response_model=SpaceOut, status_code=status.HTTP_201_CREATED)
async def post_space(db: DbSession, user: CurrentUser, payload: SpaceCreate) -> SpaceOut:
    """ESP-02: creates a shared space (the single personal one comes from ESP-01)."""
    space = await create_shared_space(
        db, user, payload.name, payload.base_currency, payload.timezone
    )
    member = await db.get(SpaceMember, (space.id, user.id))
    assert member is not None
    return _space_out(space, member)


@router.get("/spaces/{space_id}", response_model=SpaceOut)
async def get_space(db: DbSession, user: CurrentUser, space_id: uuid.UUID) -> SpaceOut:
    space, member = await _get_membership(db, user, space_id)
    return _space_out(space, member)


@router.patch("/spaces/{space_id}", response_model=SpaceOut)
async def patch_space(
    db: DbSession, user: CurrentUser, space_id: uuid.UUID, payload: SpaceUpdate
) -> SpaceOut:
    """Rename is owner-only (ESP-03)."""
    space, member = await _get_membership(db, user, space_id)
    if member.role != SpaceRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    space.name = payload.name
    await db.commit()
    await db.refresh(space)
    return _space_out(space, member)
