"""Router: transactions. Reglas en REGLAS_NEGOCIO.md (local)."""
from fastapi import APIRouter

router = APIRouter(prefix="/transactions", tags=["transactions"])
