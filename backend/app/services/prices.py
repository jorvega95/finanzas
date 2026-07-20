"""Precios de activos. Implementa INV-03, INV-04, INV-04b.

Proveedor default: CoinGecko (crédito plano: 1 llamada = 1 crédito aunque el
batch lleve 250 monedas). Alterno: CoinMarketCap. La API key jamás sale del
backend; caché server-side TTL 10 min en `asset_prices`.

Dos almacenes con dueños distintos (INV-04b):
- `asset_prices`: caché del proveedor, GLOBAL a propósito (INV-03 exige un
  solo batch por refresh para todo el sistema).
- `manual_asset_prices`: precios capturados a mano, por espacio (GLO-05).
  Ganan sobre la caché para su espacio y nunca la escriben ni la invalidan.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.investments import AssetPrice, ManualAssetPrice

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


@dataclass
class ResolvedPrice:
    """INV-04b: precio efectivo de un símbolo para un espacio, sin importar si
    viene de la caché del proveedor (`source` = coingecko/...) o de un precio
    manual del espacio (`source` = "manual")."""

    price: Decimal
    currency: str
    fetched_at: datetime
    source: str


async def get_prices(
    session: AsyncSession,
    space_id: uuid.UUID,
    symbols: list[str],
    provider: PriceProvider | None = None,
) -> dict[str, ResolvedPrice]:
    """INV-03/INV-04b: precio efectivo por símbolo para el espacio dado.

    El precio manual del espacio (si existe) gana sobre la caché del proveedor.
    La caché (TTL 10 min) es global y solo se refresca para los símbolos que
    NO tienen manual; ante fallo del proveedor se sirve el último valor
    cacheado con su fetched_at visible."""
    if not symbols:
        return {}
    provider = provider or get_provider()
    now = datetime.now(UTC)

    manual = {
        m.symbol: m
        for m in (
            (
                await session.execute(
                    select(ManualAssetPrice).where(
                        ManualAssetPrice.space_id == space_id,
                        ManualAssetPrice.symbol.in_(symbols),
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    # INV-04b: la caché global solo se consulta/refresca para lo que no es manual.
    provider_symbols = [s for s in symbols if s not in manual]

    cached = {
        p.symbol: p
        for p in (
            (
                await session.execute(
                    select(AssetPrice).where(AssetPrice.symbol.in_(provider_symbols))
                )
            )
            .scalars()
            .all()
        )
    }

    def is_stale(row: AssetPrice) -> bool:
        fetched = row.fetched_at
        if fetched.tzinfo is None:  # SQLite returns naive datetimes
            fetched = fetched.replace(tzinfo=UTC)
        return now - fetched > CACHE_TTL

    stale = [s for s in provider_symbols if s not in cached or is_stale(cached[s])]
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

    resolved: dict[str, ResolvedPrice] = {}
    for symbol in symbols:
        if symbol in manual:
            m = manual[symbol]
            resolved[symbol] = ResolvedPrice(m.price, m.currency, m.fetched_at, "manual")
        elif symbol in cached:
            c = cached[symbol]
            resolved[symbol] = ResolvedPrice(c.price, c.currency, c.fetched_at, c.source)
    return resolved


async def set_manual_price(
    session: AsyncSession,
    space_id: uuid.UUID,
    symbol: str,
    price: Decimal,
    currency: str = "MXN",
) -> ManualAssetPrice:
    """INV-04: precio capturado a mano (CETES, fondos, acciones), por espacio."""
    now = datetime.now(UTC)
    existing = await session.get(ManualAssetPrice, (space_id, symbol))
    if existing is not None:
        existing.price = price
        existing.currency = currency
        existing.fetched_at = now
        row = existing
    else:
        row = ManualAssetPrice(
            space_id=space_id, symbol=symbol, price=price, currency=currency, fetched_at=now
        )
        session.add(row)
    await session.flush()
    return row
