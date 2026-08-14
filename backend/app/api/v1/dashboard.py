"""Router: dashboard aggregates. Implements DSH-01..DSH-05."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.dates import today_in_tz
from app.core.deps import ActiveSpace, DbSession
from app.models.catalogs import ExpenseNature
from app.schemas.dashboard import (
    CategoryBreakdownRow,
    DashboardSummary,
    ForecastSummary,
    NatureDetail,
    NatureDetailItem,
    Totals,
    TrendPoint,
    UpcomingItem,
)
from app.services import dashboard as svc
from app.services import forecast as forecast_svc

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(
    db: DbSession, space_and_member: ActiveSpace, month: str | None = None
) -> DashboardSummary:
    """DSH-02/03/05 en un solo payload; agregados 100% en SQL."""
    space, _ = space_and_member
    month = month or today_in_tz(space.timezone).strftime("%Y-%m")
    start, end = svc.month_bounds(month)

    totals = await svc.monthly_totals(db, space, start, end)
    by_category = await svc.expenses_by_category(db, space, start, end)
    by_nature = await svc.expenses_by_nature(db, space, start, end)
    trend = await svc.trend(db, space, month)
    upcoming = await svc.upcoming_commitments(db, space)

    return DashboardSummary(
        month=month,
        totals=Totals(**totals),
        by_category=[CategoryBreakdownRow(**row) for row in by_category],
        by_nature=by_nature,
        trend=[TrendPoint(**point) for point in trend],
        upcoming=[UpcomingItem(**item) for item in upcoming],
    )


@router.get("/by-nature/{nature}", response_model=NatureDetail)
async def nature_detail(
    db: DbSession,
    space_and_member: ActiveSpace,
    nature: ExpenseNature,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> NatureDetail:
    """DSH-06: drill-down de una naturaleza; mismos predicados que DSH-02/03."""
    space, _ = space_and_member
    month = month or today_in_tz(space.timezone).strftime("%Y-%m")
    start, end = svc.month_bounds(month)

    detail = await svc.expenses_by_nature_detail(db, space, nature, start, end)
    return NatureDetail(
        nature=detail["nature"],
        month=month,
        total=detail["total"],
        by_category=[CategoryBreakdownRow(**row) for row in detail["by_category"]],
        items=[NatureDetailItem(**item) for item in detail["items"]],
    )


@router.get("/forecast", response_model=ForecastSummary)
async def forecast(
    db: DbSession,
    space_and_member: ActiveSpace,
    horizon_months: Annotated[int, Query(ge=1, le=24)] = 6,
    cash_adjustment: Annotated[Decimal, Query()] = Decimal("0"),
) -> ForecastSummary:
    """PRO-01..06: pronóstico de flujo a futuro y detección de sobregiro."""
    space, _ = space_and_member
    result = await forecast_svc.forecast(
        db, space, horizon_months=horizon_months, cash_adjustment=cash_adjustment
    )
    return ForecastSummary(**result)
