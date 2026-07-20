from fastapi import APIRouter

from app.api.v1 import (
    budgets,
    cards,
    catalogs,
    dashboard,
    imports,
    installments,
    investments,
    notifications,
    recurring,
    spaces,
    transactions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(spaces.router)
api_router.include_router(catalogs.router)
api_router.include_router(transactions.router)
api_router.include_router(recurring.router)
api_router.include_router(cards.router)
api_router.include_router(installments.router)
api_router.include_router(investments.router)
api_router.include_router(dashboard.router)
api_router.include_router(budgets.router)
api_router.include_router(imports.router)
api_router.include_router(notifications.router)
