"""Precios de activos. Implementa INV-03, INV-03b.

Proveedor default: CoinGecko (crédito plano, históricos 1 año).
Alterno: CoinMarketCap. La API key jamás sale del backend.
"""
from decimal import Decimal
from typing import Protocol


class PriceProvider(Protocol):
    async def get_quotes(self, symbols: list[str]) -> dict[str, Decimal]:
        """Batch de precios USD. 1 llamada por refresh del sistema, no por usuario."""
        ...


class CoinGeckoProvider:
    """INV-03: /simple/price con caché TTL 10 min."""


class CoinMarketCapProvider:
    """Proveedor alterno (quotes/latest)."""
