"""FastAPI dependencies: DB session, current user and active space.

GLO-05: every query filters by space_id. ESP-03: role matrix.
A user without membership in the requested space gets **404, not 403**,
to avoid leaking existence (mandatory test case 8 in REGLAS_NEGOCIO.md).
"""

import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_supabase_jwt
from app.db.session import SessionLocal
from app.models.spaces import Profile, Space, SpaceMember, SpaceRole
from app.services.spaces import provision_profile


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Profile:
    """Verify the Supabase JWT and lazily provision the profile (ESP-01).

    Supabase owns signup; our first sight of a user is their first
    authenticated request, so provisioning happens here.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    claims = verify_supabase_jwt(authorization.split(" ", 1)[1])
    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    metadata = claims.get("user_metadata") or {}
    display_name = metadata.get("full_name") or metadata.get("name")
    return await provision_profile(db, user_id, claims.get("email"), display_name)


CurrentUser = Annotated[Profile, Depends(get_current_user)]


async def get_active_space(
    db: DbSession,
    user: CurrentUser,
    x_space_id: Annotated[str | None, Header()] = None,
) -> tuple[Space, SpaceMember]:
    """Resolve the active space from `X-Space-Id` (default: profile's default).

    GLO-05: no membership => 404 (existence is never leaked).
    """
    raw_id = x_space_id or (str(user.default_space_id) if user.default_space_id else None)
    try:
        space_id = uuid.UUID(raw_id) if raw_id else None
    except ValueError:
        space_id = None
    if space_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

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


ActiveSpace = Annotated[tuple[Space, SpaceMember], Depends(get_active_space)]


def require_role(
    *roles: SpaceRole,
) -> Callable[..., Coroutine[Any, Any, tuple[Space, SpaceMember]]]:
    """ESP-03: member without the required role gets 403 (they do know the
    space exists); non-members never reach this point (404 above)."""

    async def checker(space_and_member: ActiveSpace) -> tuple[Space, SpaceMember]:
        _, member = space_and_member
        if member.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return space_and_member

    return checker


# Mutating data (transactions, catalogs, cards...) requires editor+ (ESP-03).
EditorSpace = Annotated[
    tuple[Space, SpaceMember], Depends(require_role(SpaceRole.owner, SpaceRole.editor))
]
# Space administration (rename/delete, members) is owner-only (ESP-03).
OwnerSpace = Annotated[tuple[Space, SpaceMember], Depends(require_role(SpaceRole.owner))]
