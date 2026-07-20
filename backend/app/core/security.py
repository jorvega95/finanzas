"""Verification of JWTs issued by Supabase Auth.

FastAPI does NOT issue tokens: it only verifies Supabase's (audience
"authenticated"). The user id (sub) maps to profiles.id (ESP-01).

Two verification modes, auto-selected:

1. **JWT Signing Keys (asimétricas, ES256/RS256)** — el default en proyectos
   nuevos de Supabase. No hay secreto que copiar: las llaves públicas se
   descargan del endpoint JWKS del proyecto
   (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) y se cachean.
   Solo requiere `SUPABASE_URL` en el .env.
2. **Legacy JWT secret (HS256)** — proyectos antiguos sin migrar (y los
   tests). Se usa si `SUPABASE_JWT_SECRET` está definido.
"""

from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient

from app.core.config import settings

# Algorithms Supabase uses for asymmetric signing keys.
JWKS_ALGORITHMS = ["ES256", "RS256"]

# PyJWT solo valida exp/iat si el claim viene en el payload: sin esto, un token
# firmado sin exp se aceptaría como eterno. Se exigen explícitamente.
REQUIRED_CLAIMS = ["exp", "iat", "sub"]


@lru_cache(maxsize=1)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    """JWKS client with built-in key caching (refetches on unknown kid)."""
    return PyJWKClient(
        f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
        lifespan=600,
    )


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    # Legacy HS256 path (old projects + test suite).
    if settings.supabase_jwt_secret:
        try:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    # Modern path: asymmetric signing keys via the project's public JWKS.
    if settings.supabase_url:
        try:
            signing_key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=JWKS_ALGORITHMS,
                audience="authenticated",
                issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
                options={"require": [*REQUIRED_CLAIMS, "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth is not configured")
