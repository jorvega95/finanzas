"""Router: investments. Reglas en REGLAS_NEGOCIO.md (local)."""

from fastapi import APIRouter

router = APIRouter(prefix="/investments", tags=["investments"])
