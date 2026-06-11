"""Verification of JWTs issued by Supabase Auth.

FastAPI does NOT issue tokens: it only verifies Supabase's (audience
"authenticated", HS256 with the project's JWT secret). The user id (sub)
maps to profiles.id (ESP-01).
"""

from typing import Any

import jwt
from fastapi import HTTPException, status

from app.core.config import settings


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    if not settings.supabase_jwt_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth is not configured")
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
