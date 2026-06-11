"""APScheduler. Jobs diarios (tz del espacio, GLO-02):

- recurrentes cada hora: idempotente (REC-02), así cada espacio genera poco
  después de su medianoche local sin un scheduler por timezone
- tipo de cambio Banxico FIX una vez al día (FX-02)
- Fase 2+: cierre de statements (TDC-07), recordatorios (REM-01),
  snapshots (INV-05, PAT-01)
"""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.spaces import Space
from app.services import fx
from app.services.recurring import generate_due_instances

logger = logging.getLogger(__name__)


async def run_recurring_job() -> None:
    """REC-02/REC-05: generate due recurring instances for every space.
    Idempotent, so running hourly is safe and covers all timezones."""
    async with SessionLocal() as session:
        spaces = (await session.execute(select(Space))).scalars().all()
        for space in spaces:
            try:
                created = await generate_due_instances(session, space)
                if created:
                    logger.info("recurring: %s instances for space %s", created, space.id)
            except Exception:
                logger.exception("recurring job failed for space %s", space.id)


async def run_card_close_job() -> None:
    """TDC-07 + REM-01: close due statements and fire due reminders. Hourly
    and idempotent, so every space closes shortly after its local midnight."""
    from app.core.dates import today_in_tz
    from app.services.budgets import check_budget_alerts
    from app.services.cards import close_due_statements
    from app.services.reminders import fire_due_reminders

    async with SessionLocal() as session:
        spaces = (await session.execute(select(Space))).scalars().all()
        for space in spaces:
            try:
                await close_due_statements(session, space)
                today = today_in_tz(space.timezone)
                # PRE-03: evaluate current-month budget alerts (idempotent).
                await check_budget_alerts(session, space, today.replace(day=1))
                await fire_due_reminders(session, today)
            except Exception:
                logger.exception("card close job failed for space %s", space.id)


async def run_fx_job() -> None:
    """FX-02: persist today's USD/MXN FIX (carry-forward on holidays)."""
    async with SessionLocal() as session:
        try:
            await fx.sync_usd_mxn_rate(session, datetime.now(UTC).date())
        except Exception:
            logger.exception("fx job failed")


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(run_recurring_job, "cron", minute=35, id="recurring")
    scheduler.add_job(run_card_close_job, "cron", minute=50, id="card_close")
    scheduler.add_job(run_fx_job, "cron", hour=18, minute=10, id="fx")  # ~12:10 MX
    return scheduler
