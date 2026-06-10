"""Router: catalogs. Reglas en REGLAS_NEGOCIO.md (local)."""
from fastapi import APIRouter

router = APIRouter(prefix="/catalogs", tags=["catalogs"])
