"""Router: dashboard aggregates. Implements DSH-01..DSH-05."""

from fastapi import APIRouter

from app.core.dates import today_in_tz
from app.core.deps import ActiveSpace, DbSession
from app.schemas.dashboard import (
    CategoryBreakdownRow,
    DashboardSummary,
    Totals,
    TrendPoint,
    UpcomingItem,
)
from app.services import dashboard as svc

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(
    db: DbSession, space_and_member: ActiveSpace, month: str | None = None
) -> DashboardSummary:
    """DSH-02/03/04/05 en un solo payload; agregados 100% en SQL."""
    space, _ = space_and_member
    month = month or today_in_tz(space.timezone).strftime("%Y-%m")
    start, end = svc.month_bounds(month)

    accrual = await svc.monthly_totals(db, space, start, end)
    cash_flow = await svc.cash_flow_totals(db, space, start, end)
    by_category = await svc.expenses_by_category(db, space, start, end)
    by_nature = await svc.expenses_by_nature(db, space, start, end)
    trend = await svc.trend(db, space, month)
    upcoming = await svc.upcoming_commitments(db, space)

    return DashboardSummary(
        month=month,
        accrual=Totals(**accrual),
        cash_flow=Totals(**cash_flow),
        by_category=[CategoryBreakdownRow(**row) for row in by_category],
        by_nature=by_nature,
        trend=[TrendPoint(**point) for point in trend],
        upcoming=[UpcomingItem(**item) for item in upcoming],
    )
