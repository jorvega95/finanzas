"""Router: profile bootstrap and spaces. Implements ESP-01..ESP-03, GLO-05."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.spaces import Profile, Space, SpaceInvite, SpaceMember, SpaceRole
from app.schemas.spaces import (
    InviteClaim,
    InviteCreate,
    InviteOut,
    MemberOut,
    MemberRoleUpdate,
    MeOut,
    ProfileOut,
    SpaceCreate,
    SpaceDelete,
    SpaceOut,
    SpaceUpdate,
)
from app.services import spaces as svc
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


async def _require_owner(
    db: DbSession, user: Profile, space_id: uuid.UUID
) -> tuple[Space, SpaceMember]:
    space, member = await _get_membership(db, user, space_id)
    if member.role != SpaceRole.owner:
        # ESP-03: gestionar miembros es solo del owner.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el owner gestiona miembros")
    return space, member


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    db: DbSession, user: CurrentUser, space_id: uuid.UUID, payload: SpaceDelete
) -> None:
    """ESP-06: borra el espacio compartido (confirmación con nombre exacto)."""
    space, _ = await _require_owner(db, user, space_id)
    await svc.delete_space(db, space, payload.confirm_name)


@router.get("/spaces/{space_id}/members", response_model=list[MemberOut])
async def list_members(db: DbSession, user: CurrentUser, space_id: uuid.UUID) -> list[MemberOut]:
    space, _ = await _get_membership(db, user, space_id)
    rows = await db.execute(
        select(SpaceMember, Profile)
        .join(Profile, SpaceMember.user_id == Profile.id)
        .where(SpaceMember.space_id == space.id)
        .order_by(SpaceMember.joined_at)
    )
    return [
        MemberOut(
            user_id=member.user_id,
            display_name=profile.display_name,
            email=profile.email,
            role=member.role,
        )
        for member, profile in rows.all()
    ]


@router.patch("/spaces/{space_id}/members/{member_id}", response_model=MemberOut)
async def change_role(
    db: DbSession,
    user: CurrentUser,
    space_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: MemberRoleUpdate,
) -> MemberOut:
    """ESP-03/ESP-05: cambiar roles es del owner; el último owner no baja."""
    space, _ = await _require_owner(db, user, space_id)
    member = await db.get(SpaceMember, (space.id, member_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")
    member = await svc.change_member_role(db, space, member, payload.role)
    profile = await db.get(Profile, member_id)
    return MemberOut(
        user_id=member.user_id,
        display_name=profile.display_name if profile else "",
        email=profile.email if profile else None,
        role=member.role,
    )


@router.delete("/spaces/{space_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    db: DbSession, user: CurrentUser, space_id: uuid.UUID, member_id: uuid.UUID
) -> None:
    """ESP-05/ESP-07: el owner remueve a cualquiera; un miembro puede salirse
    a sí mismo. Las transacciones del removido permanecen."""
    if member_id == user.id:
        space, member = await _get_membership(db, user, space_id)
    else:
        space, _ = await _require_owner(db, user, space_id)
        found = await db.get(SpaceMember, (space.id, member_id))
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")
        member = found
    await svc.remove_member(db, space, member)


@router.get("/spaces/{space_id}/invites", response_model=list[InviteOut])
async def list_invites(db: DbSession, user: CurrentUser, space_id: uuid.UUID) -> list[SpaceInvite]:
    space, _ = await _require_owner(db, user, space_id)
    rows = await db.execute(
        select(SpaceInvite)
        .where(SpaceInvite.space_id == space.id, SpaceInvite.claimed_at.is_(None))
        .order_by(SpaceInvite.created_at.desc())
    )
    return list(rows.scalars().all())


@router.post(
    "/spaces/{space_id}/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED
)
async def create_invite(
    db: DbSession, user: CurrentUser, space_id: uuid.UUID, payload: InviteCreate
) -> SpaceInvite:
    """ESP-04: invitación por email (token de un solo uso, 7 días)."""
    space, _ = await _require_owner(db, user, space_id)
    return await svc.create_invite(db, space, user.id, payload.email, payload.role)


@router.post("/invites/claim", response_model=SpaceOut)
async def claim_invite(db: DbSession, user: CurrentUser, payload: InviteClaim) -> SpaceOut:
    """ESP-04: reclamar invitación con el token (el email debe coincidir)."""
    space = await svc.claim_invite(db, user, payload.token)
    member = await db.get(SpaceMember, (space.id, user.id))
    assert member is not None
    return _space_out(space, member)
