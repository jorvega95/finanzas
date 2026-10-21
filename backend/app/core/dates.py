"""Business-date helpers. Implements GLO-02: 'today' is a `date` resolved in
the space timezone; business logic never touches datetimes."""

from datetime import date, datetime
from zoneinfo import ZoneInfo


def today_in_tz(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def local_hour(tz: str) -> int:
    """REM-08: current hour in the space timezone (desktop notice window)."""
    return datetime.now(ZoneInfo(tz)).hour
