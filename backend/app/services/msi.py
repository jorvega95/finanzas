"""Planes MSI. Implementa MSI-01..MSI-09.

Invariante MSI-02 (test property-based obligatorio): sum(cuotas) == total exacto.
"""
from decimal import Decimal


def build_installments(total: Decimal, months: int) -> list[Decimal]:
    """MSI-02: monthly = ROUND_FLOOR(total/months, 2); última cuota absorbe residuo."""
    raise NotImplementedError("MSI-02")
