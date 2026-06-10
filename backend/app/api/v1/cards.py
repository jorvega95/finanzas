"""Router: cards. Reglas en REGLAS_NEGOCIO.md (local)."""
from fastapi import APIRouter

router = APIRouter(prefix="/cards", tags=["cards"])
