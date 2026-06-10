"""Verificación de JWT emitidos por Supabase Auth.

FastAPI NO emite tokens: solo verifica los de Supabase (audience
"authenticated"). El user id (sub) mapea a profiles.id (ESP-01).
"""
import jwt
from fastapi import HTTPException, status

from app.core.config import settings


def verify_supabase_jwt(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
