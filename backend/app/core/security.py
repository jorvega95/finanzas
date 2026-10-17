"""Verification of HS256 bearer JWTs (AUTH_MODE=jwt, GLO-07).

In the default local mode (AUTH_MODE=local) no token is required at all; see
`app.core.deps.get_current_user`. This path remains for the test suite and a
possible future remote/mobile client. The user id (`sub`) maps to profiles.id
(ESP-01).
"""

from typing import Any

import jwt
from fastapi import HTTPException, status

from app.core.config import settings

# PyJWT solo valida exp/iat si el claim viene en el payload: sin esto, un token
# firmado sin exp se aceptaría como eterno. Se exigen explícitamente.
REQUIRED_CLAIMS = ["exp", "iat", "sub"]


def verify_jwt(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
