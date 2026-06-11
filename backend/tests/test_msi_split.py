"""Fase 2: MSI-02 (caso obligatorio 3) — reparto de cuotas, property-based."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.msi import split_installments


def test_msi02_canonical_example():
    """1000.00 / 3 ⇒ 333.33, 333.33, 333.34 (ROUND_FLOOR + residuo al final)."""
    cuotas = split_installments(Decimal("1000.00"), 3)
    assert cuotas == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert sum(cuotas) == Decimal("1000.00")


@settings(max_examples=1000)
@given(
    total_cents=st.integers(min_value=1, max_value=10_000_000_00),
    months=st.integers(min_value=2, max_value=60),
)
def test_msi02_sum_equals_total_property(total_cents: int, months: int):
    """Invariante MSI-02: Σ cuotas == total exacto, en 1000 combinaciones."""
    total = Decimal(total_cents) / Decimal(100)
    cuotas = split_installments(total, months)
    assert len(cuotas) == months
    assert sum(cuotas) == total
    # ROUND_FLOOR: todas las cuotas intermedias son iguales y <= total/months.
    assert len({c for c in cuotas[:-1]}) <= 1
    if months > 1:
        assert cuotas[-1] >= cuotas[0]
    # GLO-01: exactamente 2 decimales.
    assert all(c == c.quantize(Decimal("0.01")) for c in cuotas)
    assert all(c >= 0 for c in cuotas)
