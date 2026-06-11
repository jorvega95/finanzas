"""Space and profile services. Implements ESP-01..ESP-07, GLO-05."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spaces import Profile, Space, SpaceInvite, SpaceMember, SpaceRole, SpaceType
from app.services.catalogs import seed_catalogs

INVITE_TTL = timedelta(days=7)  # ESP-04


async def provision_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
    email: str | None,
    display_name: str | None,
) -> Profile:
    """ESP-01: first authenticated request creates profile + personal space
    "Personal" + owner membership + seed catalogs (CAT-02). Idempotent."""
    profile = await session.get(Profile, user_id)
    if profile is not None:
        return profile

    profile = Profile(
        id=user_id,
        email=email,
        display_name=display_name or (email.split("@")[0] if email else "Usuario"),
    )
    session.add(profile)
    await session.flush()

    space = Space(name="Personal", type=SpaceType.personal, created_by=user_id)
    session.add(space)
    await session.flush()
    session.add(SpaceMember(space_id=space.id, user_id=user_id, role=SpaceRole.owner))
    seed_catalogs(session, space.id, user_id)

    profile.default_space_id = space.id
    await session.flush()
    # ESP-04: pending invites to this email are claimed at registration.
    if email:
        await _claim_pending_invites_for_email(session, profile, email)
    await session.commit()
    await session.refresh(profile)
    return profile


async def _claim_pending_invites_for_email(
    session: AsyncSession, profile: Profile, email: str
) -> None:
    now = datetime.now(UTC)
    invites = (
        (
            await session.execute(
                select(SpaceInvite).where(
                    func.lower(SpaceInvite.email) == email.lower(),
                    SpaceInvite.claimed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for invite in invites:
        expires = invite.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < now:
            continue
        existing = await session.get(SpaceMember, (invite.space_id, profile.id))
        if existing is None:
            session.add(SpaceMember(space_id=invite.space_id, user_id=profile.id, role=invite.role))
        invite.claimed_at = now  # single use (ESP-04)
    await session.flush()


async def create_shared_space(
    session: AsyncSession,
    creator: Profile,
    name: str,
    base_currency: str = "MXN",
    timezone: str = "America/Mexico_City",
) -> Space:
    """ESP-02: a user may own N shared spaces (personal is created only by
    provisioning). CAT-02 seeds apply to every new space."""
    space = Space(
        name=name,
        type=SpaceType.shared,
        base_currency=base_currency,
        timezone=timezone,
        created_by=creator.id,
    )
    session.add(space)
    await session.flush()
    session.add(SpaceMember(space_id=space.id, user_id=creator.id, role=SpaceRole.owner))
    seed_catalogs(session, space.id, creator.id)
    await session.commit()
    await session.refresh(space)
    return space


async def create_invite(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    email: str,
    role: SpaceRole,
) -> SpaceInvite:
    """ESP-04: token de un solo uso, 7 días; reemplaza la invitación
    pendiente al mismo email. Solo espacios compartidos reciben miembros."""
    if space.type == SpaceType.personal:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El espacio personal no admite miembros (ESP-01)",
        )
    pending = (
        (
            await session.execute(
                select(SpaceInvite).where(
                    SpaceInvite.space_id == space.id,
                    func.lower(SpaceInvite.email) == email.lower(),
                    SpaceInvite.claimed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for invite in pending:
        await session.delete(invite)

    invite = SpaceInvite(
        space_id=space.id,
        email=email,
        role=role,
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + INVITE_TTL,
        created_by=created_by,
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return invite


async def claim_invite(session: AsyncSession, user: Profile, token: str) -> Space:
    """ESP-04: reclamar por token. Un solo uso; el email debe coincidir.
    Cualquier fallo es 404 para no filtrar existencia (GLO-05)."""
    invite = await session.scalar(select(SpaceInvite).where(SpaceInvite.token == token))
    not_found = HTTPException(status.HTTP_404_NOT_FOUND, "Invitación no encontrada")
    if invite is None or invite.claimed_at is not None:
        raise not_found
    expires = invite.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        raise not_found
    if not user.email or user.email.lower() != invite.email.lower():
        raise not_found

    existing = await session.get(SpaceMember, (invite.space_id, user.id))
    if existing is None:
        session.add(SpaceMember(space_id=invite.space_id, user_id=user.id, role=invite.role))
    invite.claimed_at = datetime.now(UTC)
    await session.commit()
    space = await session.get(Space, invite.space_id)
    assert space is not None
    return space


async def _owner_count(session: AsyncSession, space_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(SpaceMember)
        .where(SpaceMember.space_id == space_id, SpaceMember.role == SpaceRole.owner)
    )
    return count or 0


async def change_member_role(
    session: AsyncSession, space: Space, member: SpaceMember, new_role: SpaceRole
) -> SpaceMember:
    """ESP-05: el último owner no puede degradarse; primero transfiere."""
    if (
        member.role == SpaceRole.owner
        and new_role != SpaceRole.owner
        and await _owner_count(session, space.id) <= 1
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El espacio necesita al menos un owner; transfiere la propiedad primero",
        )
    member.role = new_role
    await session.commit()
    return member


async def remove_member(session: AsyncSession, space: Space, member: SpaceMember) -> None:
    """ESP-05: el último owner no puede salir. ESP-07: sus transacciones
    permanecen con created_by intacto (nada que tocar: la FK persiste)."""
    if member.role == SpaceRole.owner and await _owner_count(session, space.id) <= 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El último owner no puede salir; transfiere la propiedad primero",
        )
    await session.delete(member)
    await session.commit()


async def delete_space(session: AsyncSession, space: Space, confirm_name: str) -> None:
    """ESP-06: solo espacios compartidos, con confirmación explícita (nombre
    exacto); borra en cascada y notifica a los miembros."""
    from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus

    if space.type == SpaceType.personal:
        # ESP-01: el personal no puede eliminarse.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "El espacio personal no puede eliminarse"
        )
    if confirm_name != space.name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Escribe el nombre exacto del espacio para confirmar",
        )
    members = (
        (await session.execute(select(SpaceMember).where(SpaceMember.space_id == space.id)))
        .scalars()
        .all()
    )
    # ESP-06: notificación a los miembros — va a su espacio personal para
    # sobrevivir al borrado en cascada del espacio eliminado.
    for member in members:
        profile = await session.get(Profile, member.user_id)
        if profile is None or profile.default_space_id is None:
            continue
        session.add(
            Reminder(
                space_id=profile.default_space_id,
                kind=ReminderKind.custom,
                ref_id=member.user_id,
                offset_days=0,
                fire_at=datetime.now(UTC).date(),
                channel=ReminderChannel.in_app,
                message=f'El espacio "{space.name}" fue eliminado por su owner',
                status=ReminderStatus.sent,
            )
        )
    # Reset default_space_id pointing at the deleted space (fallback ESP-01).
    profiles = (
        (await session.execute(select(Profile).where(Profile.default_space_id == space.id)))
        .scalars()
        .all()
    )
    for profile in profiles:
        personal = await session.scalar(
            select(Space)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(
                SpaceMember.user_id == profile.id,
                Space.type == SpaceType.personal,
            )
        )
        profile.default_space_id = personal.id if personal else None
    await session.delete(space)
    await session.commit()


async def list_user_spaces(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Space, SpaceMember]]:
    rows = await session.execute(
        select(Space, SpaceMember)
        .join(SpaceMember, SpaceMember.space_id == Space.id)
        .where(SpaceMember.user_id == user_id)
        .order_by(Space.created_at)
    )
    return [(space, member) for space, member in rows.all()]
