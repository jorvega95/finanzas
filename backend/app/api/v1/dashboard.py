"""Router: dashboard. Reglas en REGLAS_NEGOCIO.md (local)."""

from fastapi import APIRouter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
