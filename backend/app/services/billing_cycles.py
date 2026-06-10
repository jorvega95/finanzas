"""Ciclos de facturación de TDC. Implementa TDC-02..TDC-07, TDC-11.

El código más delicado del proyecto: tests primero (freezegun).
Solo `date`, nunca `datetime` (GLO-02).
"""
from datetime import date


def statement_cutoff(statement_day: int | str, year: int, month: int) -> date:
    """TDC-02: corte del mes = min(d, último día del mes); 'last' = último día."""
    raise NotImplementedError("TDC-02")


def cycle_for_purchase(purchase_date: date, card) -> tuple[date, date]:
    """TDC-03/TDC-05: ciclo [corte_anterior+1, corte] al que se asigna una compra.

    Respeta card.cutoff_day_policy ('include' | 'next_cycle') cuando
    purchase_date == period_end.
    """
    raise NotImplementedError("TDC-05")


def due_date_for(period_end: date, card) -> date:
    """TDC-04: period_end + payment_due_days, o primer payment_day posterior."""
    raise NotImplementedError("TDC-04")
