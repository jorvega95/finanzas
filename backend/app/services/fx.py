"""Tipos de cambio. Implementa FX-01..FX-05.

Único punto de conversión del sistema: nadie más convierte monedas.
Tasa congelada por transacción (FX-03); mark-to-market para inversiones y
saldos/deudas de cuentas en el patrimonio (FX-04).
"""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.fx import ExchangeRate

# Banxico SIE series SF43718: USD/MXN FIX (FX-02).
BANXICO_FIX_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43718/datos/oportuno"

RATE_PRECISION = Decimal("0.00000001")


async def get_rate(session: AsyncSession, base: str, quote: str, on_date: date) -> Decimal | None:
    """FX-03: rate of `on_date` or the closest previous one. Returns the rate
    to convert 1 `base` into `quote`; None if no rate is known."""
    if base == quote:
        return Decimal(1)

    direct = await session.scalar(
        select(ExchangeRate.rate)
        .where(
            ExchangeRate.base == base,
            ExchangeRate.quote == quote,
            ExchangeRate.date <= on_date,
        )
        .order_by(ExchangeRate.date.desc())
        .limit(1)
    )
    if direct is not None:
        return Decimal(direct)

    inverse = await session.scalar(
        select(ExchangeRate.rate)
        .where(
            ExchangeRate.base == quote,
            ExchangeRate.quote == base,
            ExchangeRate.date <= on_date,
        )
        .order_by(ExchangeRate.date.desc())
        .limit(1)
    )
    if inverse is not None and Decimal(inverse) != 0:
        return (Decimal(1) / Decimal(inverse)).quantize(RATE_PRECISION, ROUND_HALF_EVEN)
    return None


async def has_rate_on(session: AsyncSession, base: str, quote: str, on_date: date) -> bool:
    """REC-08: whether a rate dated exactly `on_date` exists (either
    direction; a carry-forward row counts)."""
    if base == quote:
        return True
    found = await session.scalar(
        select(ExchangeRate.date)
        .where(
            ((ExchangeRate.base == base) & (ExchangeRate.quote == quote))
            | ((ExchangeRate.base == quote) & (ExchangeRate.quote == base)),
            ExchangeRate.date == on_date,
        )
        .limit(1)
    )
    return found is not None


async def convert(
    session: AsyncSession, amount: Decimal, currency: str, target: str, on_date: date
) -> Decimal | None:
    """REC-08: `amount` in `currency` expressed in `target` with the rate of
    `on_date` (or the closest previous), HALF_EVEN to cents. None without a
    known rate."""
    if currency == target:
        return Decimal(amount)
    rate = await get_rate(session, currency, target, on_date)
    if rate is None:
        return None
    return (Decimal(amount) * rate).quantize(Decimal("0.01"), ROUND_HALF_EVEN)


async def mark_to_market(
    session: AsyncSession, amount: Decimal, currency: str, base: str, on_date: date
) -> Decimal | None:
    """FX-04: value `amount` (in `currency`) in `base` with the rate of the
    valuation day. None when no rate is known (the caller reports it)."""
    if currency == base:
        return Decimal(amount)
    rate = await get_rate(session, currency, base, on_date)
    if rate is None:
        return None
    return (Decimal(amount) * rate).quantize(Decimal("0.01"), ROUND_HALF_EVEN)


async def upsert_rate(
    session: AsyncSession,
    base: str,
    quote: str,
    on_date: date,
    rate: Decimal,
    is_carry_forward: bool = False,
    source: str = "banxico",
) -> None:
    """Idempotent: re-running the FX job for the same day never duplicates."""
    existing = await session.get(ExchangeRate, (base, quote, on_date))
    if existing is not None:
        existing.rate = rate
        existing.is_carry_forward = is_carry_forward
        existing.source = source
    else:
        session.add(
            ExchangeRate(
                base=base,
                quote=quote,
                date=on_date,
                rate=rate,
                is_carry_forward=is_carry_forward,
                source=source,
            )
        )
    await session.flush()


async def fetch_banxico_fix(client: httpx.AsyncClient | None = None) -> tuple[date, Decimal]:
    """Fetch the latest published USD/MXN FIX from Banxico SIE (FX-02)."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        res = await client.get(BANXICO_FIX_URL, headers={"Bmx-Token": settings.banxico_token})
        res.raise_for_status()
        dato = res.json()["bmx"]["series"][0]["datos"][-1]
        day, month, year = dato["fecha"].split("/")
        return date(int(year), int(month), int(day)), Decimal(dato["dato"])
    finally:
        if own_client:
            await client.aclose()


async def sync_usd_mxn_rate(
    session: AsyncSession, today: date, client: httpx.AsyncClient | None = None
) -> None:
    """FX-02 daily job body: persist today's USD/MXN rate. On non-business
    days the last published rate is stored under today's date, flagged
    `is_carry_forward`."""
    published_date, rate = await fetch_banxico_fix(client)
    await upsert_rate(session, "USD", "MXN", published_date, rate)
    if published_date != today:
        await upsert_rate(session, "USD", "MXN", today, rate, is_carry_forward=True)
    await session.commit()
