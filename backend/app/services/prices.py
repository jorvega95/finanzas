"""Precios de activos. Implementa INV-03, INV-04.

Proveedor default: CoinGecko (crédito plano: 1 llamada = 1 crédito aunque el
batch lleve 250 monedas). Alterno: CoinMarketCap. La API key jamás sale del
backend; caché server-side TTL 10 min en `asset_prices`.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.investments import AssetPrice

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(minutes=10)  # INV-03
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


class PriceProvider(Protocol):
    async def get_quotes(self, symbols: list[str]) -> dict[str, Decimal]:
        """Batch de precios USD. 1 llamada por refresh del sistema, no por usuario."""
        ...


class CoinGeckoProvider:
    """INV-03: /simple/price en un solo batch."""

    async def get_quotes(self, symbols: list[str]) -> dict[str, Decimal]:
        params = {"ids": ",".join(symbols), "vs_currencies": "usd"}
        headers = {}
        if settings.coingecko_api_key:
            headers["x-cg-demo-api-key"] = settings.coingecko_api_key
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(COINGECKO_URL, params=params, headers=headers)
            res.raise_for_status()
            data = res.json()
        return {
            symbol: Decimal(str(payload["usd"]))
            for symbol, payload in data.items()
            if "usd" in payload
        }


class CoinMarketCapProvider:
    """Proveedor alterno (quotes/latest). Mismo contrato PriceProvider."""

    async def get_quotes(self, symbols: list[str]) -> dict[str, Decimal]:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest",
                params={"slug": ",".join(symbols)},
                headers={"X-CMC_PRO_API_KEY": settings.coinmarketcap_api_key},
            )
            res.raise_for_status()
            data = res.json()["data"]
        return {item["slug"]: Decimal(str(item["quote"]["USD"]["price"])) for item in data.values()}


_default_provider: PriceProvider = CoinGeckoProvider()


def get_provider() -> PriceProvider:
    return _default_provider


async def get_prices(
    session: AsyncSession, symbols: list[str], provider: PriceProvider | None = None
) -> dict[str, AssetPrice]:
    """INV-03: sirve de caché (TTL 10 min); ante fallo del proveedor se sirve
    el último precio cacheado con su fetched_at visible. Los precios manuales
    (INV-04, source='manual') nunca se sobreescriben aquí."""
    if not symbols:
        return {}
    provider = provider or get_provider()
    now = datetime.now(UTC)

    cached = {
        p.symbol: p
        for p in (
            (await session.execute(select(AssetPrice).where(AssetPrice.symbol.in_(symbols))))
            .scalars()
            .all()
        )
    }

    def is_stale(row: AssetPrice) -> bool:
        if row.source == "manual":
            return False  # INV-04: manual prices live until the user updates.
        fetched = row.fetched_at
        if fetched.tzinfo is None:  # SQLite returns naive datetimes
            fetched = fetched.replace(tzinfo=UTC)
        return now - fetched > CACHE_TTL

    stale = [s for s in symbols if s not in cached or is_stale(cached[s])]
    if stale:
        try:
            quotes = await provider.get_quotes(stale)
        except Exception:
            logger.exception("price provider failed; serving cached prices")
            quotes = {}
        for symbol, price in quotes.items():
            existing = cached.get(symbol)
            if existing is not None:
                existing.price = price
                existing.fetched_at = now
                existing.source = "coingecko"
            else:
                row = AssetPrice(symbol=symbol, price=price, currency="USD", fetched_at=now)
                session.add(row)
                cached[symbol] = row
        if quotes:
            # The cache must survive read-only requests (INV-03).
            await session.commit()
    return {s: cached[s] for s in symbols if s in cached}


async def set_manual_price(
    session: AsyncSession, symbol: str, price: Decimal, currency: str = "MXN"
) -> AssetPrice:
    """INV-04: precio capturado a mano (CETES, fondos, acciones)."""
    now = datetime.now(UTC)
    existing = await session.get(AssetPrice, symbol)
    if existing is not None:
        existing.price = price
        existing.currency = currency
        existing.fetched_at = now
        existing.source = "manual"
        row = existing
    else:
        row = AssetPrice(
            symbol=symbol, price=price, currency=currency, fetched_at=now, source="manual"
        )
        session.add(row)
    await session.flush()
    return row
