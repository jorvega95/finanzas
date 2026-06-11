"""Space and profile services. Implements ESP-01, ESP-02, GLO-05."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spaces import Profile, Space, SpaceMember, SpaceRole, SpaceType
from app.services.catalogs import seed_catalogs


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
    await session.commit()
    await session.refresh(profile)
    return profile


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
