"""Fase 2 tests (escritos ANTES de implementar): motor de ciclos TDC.

Casos obligatorios 1 y 2 de REGLAS_NEGOCIO.md + edge cases de CLAUDE.md:
- corte `last` en febrero (bisiesto y no), corte 28 en todos los meses
- compra exactamente el día de corte con ambas `cutoff_day_policy`
"""

from datetime import date

import pytest

from app.services.billing_cycles import (
    CardCycleSpec,
    cycle_for_purchase,
    due_date_for,
    next_cutoff,
    statement_cutoff,
)


def card(
    statement_day: int | str = 15,
    cutoff_day_policy: str = "include",
    payment_due_days: int | None = 20,
    payment_day: int | str | None = None,
) -> CardCycleSpec:
    return CardCycleSpec(
        statement_day=statement_day,
        cutoff_day_policy=cutoff_day_policy,
        payment_due_days=payment_due_days,
        payment_day=payment_day,
    )


# --- TDC-02: día de corte -----------------------------------------------------


def test_tdc02_statement_cutoff_regular_day():
    assert statement_cutoff(15, 2026, 6) == date(2026, 6, 15)
    assert statement_cutoff(28, 2026, 2) == date(2026, 2, 28)


def test_tdc02_cutoff_last_february_leap_and_non_leap():
    """Caso obligatorio 1: corte `last` en febrero bisiesto y no bisiesto."""
    assert statement_cutoff("last", 2024, 2) == date(2024, 2, 29)  # bisiesto
    assert statement_cutoff("last", 2026, 2) == date(2026, 2, 28)  # no bisiesto
    assert statement_cutoff("last", 2026, 4) == date(2026, 4, 30)
    assert statement_cutoff("last", 2026, 12) == date(2026, 12, 31)


def test_tdc02_cutoff_28_in_all_months():
    """Caso obligatorio 1: corte 28 existe en todos los meses."""
    for month in range(1, 13):
        assert statement_cutoff(28, 2026, month) == date(2026, month, 28)
        assert statement_cutoff(28, 2024, month).day == 28


# --- TDC-03/TDC-05: asignación de compra a ciclo ------------------------------


def test_tdc05_purchase_mid_cycle():
    """Compra después del corte de junio (día 15) cae en el ciclo que cierra
    el 15 de julio: [16-jun, 15-jul]."""
    start, end = cycle_for_purchase(date(2026, 6, 20), card(statement_day=15))
    assert (start, end) == (date(2026, 6, 16), date(2026, 7, 15))

    start, end = cycle_for_purchase(date(2026, 6, 10), card(statement_day=15))
    assert (start, end) == (date(2026, 5, 16), date(2026, 6, 15))


def test_tdc05_purchase_on_cutoff_day_include_policy():
    """Caso obligatorio 2a: compra el día del corte con policy `include`
    pertenece al ciclo que cierra ese día."""
    start, end = cycle_for_purchase(
        date(2026, 6, 15), card(statement_day=15, cutoff_day_policy="include")
    )
    assert (start, end) == (date(2026, 5, 16), date(2026, 6, 15))


def test_tdc05_purchase_on_cutoff_day_next_cycle_policy():
    """Caso obligatorio 2b: con policy `next_cycle` la compra del día del
    corte abre el siguiente ciclo."""
    start, end = cycle_for_purchase(
        date(2026, 6, 15), card(statement_day=15, cutoff_day_policy="next_cycle")
    )
    assert (start, end) == (date(2026, 6, 16), date(2026, 7, 15))


def test_tdc03_cycle_boundaries_with_last_cutoff():
    """Corte `last`: el ciclo de marzo es [1-mar, 31-mar]; en feb bisiesto
    [1-feb, 29-feb]."""
    start, end = cycle_for_purchase(date(2026, 3, 10), card(statement_day="last"))
    assert (start, end) == (date(2026, 3, 1), date(2026, 3, 31))

    start, end = cycle_for_purchase(date(2024, 2, 10), card(statement_day="last"))
    assert (start, end) == (date(2024, 2, 1), date(2024, 2, 29))


def test_tdc03_cycle_with_cutoff_31_in_short_months():
    """Corte capturado como `last` y compra en mes corto tras mes largo:
    [1-may, 31-may] para compra el 15-may; para corte 28: [marzo: 1-mar(=29-feb+1)]."""
    spec = card(statement_day=28)
    start, end = cycle_for_purchase(date(2026, 3, 5), spec)
    assert (start, end) == (date(2026, 3, 1), date(2026, 3, 28))
    # En febrero no bisiesto: ciclo [29-ene, 28-feb].
    start, end = cycle_for_purchase(date(2026, 2, 10), spec)
    assert (start, end) == (date(2026, 1, 29), date(2026, 2, 28))


# --- TDC-04: fecha límite -----------------------------------------------------


def test_tdc04_due_date_with_payment_due_days():
    """Caso obligatorio 1: `last` + payment_due_days=20 en feb bisiesto y no."""
    spec = card(statement_day="last", payment_due_days=20)
    assert due_date_for(date(2024, 2, 29), spec) == date(2024, 3, 20)  # bisiesto
    assert due_date_for(date(2026, 2, 28), spec) == date(2026, 3, 20)
    assert due_date_for(date(2026, 12, 31), spec) == date(2027, 1, 20)


def test_tdc04_due_date_with_payment_day():
    """payment_day: primer día N estrictamente posterior al corte."""
    spec = card(statement_day=15, payment_due_days=None, payment_day=5)
    assert due_date_for(date(2026, 6, 15), spec) == date(2026, 7, 5)
    # payment_day 'last': el primer fin de mes estrictamente posterior.
    spec = card(statement_day=15, payment_due_days=None, payment_day="last")
    assert due_date_for(date(2026, 6, 15), spec) == date(2026, 6, 30)
    # Si el corte ES fin de mes, va al fin del mes siguiente (feb corto).
    spec = card(statement_day="last", payment_due_days=None, payment_day="last")
    assert due_date_for(date(2026, 1, 31), spec) == date(2026, 2, 28)
    # payment_day fuera de 1-28 es inválido por TDC-01.
    spec = card(statement_day="last", payment_due_days=None, payment_day=30)
    with pytest.raises(ValueError):
        due_date_for(date(2026, 1, 31), spec)


# --- next_cutoff (proyección MSI-04) ------------------------------------------


def test_next_cutoff_projection():
    spec = card(statement_day=31)  # capturado como 'last' en la UI; aquí int>28 prohibido
    # statement_day se limita a 1-28 o 'last' (TDC-02): 31 inválido.
    with pytest.raises(ValueError):
        statement_cutoff(31, 2026, 6)

    spec = card(statement_day="last")
    assert next_cutoff(date(2026, 1, 31), spec) == date(2026, 2, 28)
    assert next_cutoff(date(2026, 2, 28), spec) == date(2026, 3, 31)

    spec = card(statement_day=15)
    assert next_cutoff(date(2026, 12, 15), spec) == date(2027, 1, 15)


def test_statement_day_invalid_values():
    with pytest.raises(ValueError):
        statement_cutoff(0, 2026, 1)
    with pytest.raises(ValueError):
        statement_cutoff(29, 2026, 1)
    with pytest.raises(ValueError):
        statement_cutoff("ultimo", 2026, 1)
