"""Ciclos de facturación de TDC. Implementa TDC-02..TDC-05.

El código más delicado del proyecto: tests primero (tests/test_billing_cycles.py).
Solo `date`, nunca `datetime` (GLO-02). Funciones puras: la persistencia vive
en services/cards.py.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

StatementDay = int | str  # 1-28 o "last" (TDC-02)


@dataclass(frozen=True)
class CardCycleSpec:
    """Subconjunto de la tarjeta que necesita el motor de ciclos.

    `statement_day`: 1-28 o "last". `cutoff_day_policy`: include | next_cycle
    (TDC-05). Exactamente uno de `payment_due_days` (1-30) o `payment_day`
    (1-28 o "last") debe estar presente (TDC-01/TDC-04).
    """

    statement_day: StatementDay
    cutoff_day_policy: str = "include"
    payment_due_days: int | None = None
    payment_day: StatementDay | None = None


def _validate_day(day: StatementDay) -> None:
    if isinstance(day, str):
        if day != "last":
            raise ValueError(f"statement_day inválido: {day!r} (1-28 o 'last')")
    elif not 1 <= day <= 28:
        raise ValueError(f"statement_day inválido: {day} (1-28 o 'last')")


def statement_cutoff(statement_day: StatementDay, year: int, month: int) -> date:
    """TDC-02: corte del mes M = min(d, último_día(M)); 'last' = último día.

    Con el dominio restringido a 1-28 o 'last' el `min` solo actúa para
    'last', pero se conserva por robustez.
    """
    _validate_day(statement_day)
    last_day = calendar.monthrange(year, month)[1]
    if statement_day == "last":
        return date(year, month, last_day)
    return date(year, month, min(int(statement_day), last_day))


def next_cutoff(after: date, card: CardCycleSpec) -> date:
    """Primer corte estrictamente posterior a `after` (proyección MSI-04)."""
    year, month = after.year, after.month
    cutoff = statement_cutoff(card.statement_day, year, month)
    while cutoff <= after:
        month += 1
        if month == 13:
            month, year = 1, year + 1
        cutoff = statement_cutoff(card.statement_day, year, month)
    return cutoff


def cutoff_on_or_after(d: date, card: CardCycleSpec) -> date:
    """Primer corte >= d."""
    cutoff = statement_cutoff(card.statement_day, d.year, d.month)
    if cutoff >= d:
        return cutoff
    return next_cutoff(d, card)


def previous_cutoff(cutoff: date, card: CardCycleSpec) -> date:
    """Corte inmediato anterior a `cutoff`."""
    year, month = cutoff.year, cutoff.month
    candidate = statement_cutoff(card.statement_day, year, month)
    if candidate >= cutoff:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
        candidate = statement_cutoff(card.statement_day, year, month)
    return candidate


def cycle_for_cutoff(cutoff: date, card: CardCycleSpec) -> tuple[date, date]:
    """TDC-03: el ciclo que cierra en C abarca [corte_anterior + 1 día, C]."""
    return previous_cutoff(cutoff, card) + timedelta(days=1), cutoff


def cycle_for_purchase(purchase_date: date, card: CardCycleSpec) -> tuple[date, date]:
    """TDC-05: la compra con fecha t va al statement cuyo period_end es el
    primer corte >= t; si t == corte, decide `cutoff_day_policy`."""
    cutoff = cutoff_on_or_after(purchase_date, card)
    if cutoff == purchase_date and card.cutoff_day_policy == "next_cycle":
        cutoff = next_cutoff(cutoff, card)
    return cycle_for_cutoff(cutoff, card)


def due_date_for(period_end: date, card: CardCycleSpec) -> date:
    """TDC-04: period_end + payment_due_days, o el primer payment_day
    estrictamente posterior a period_end (ajustado si el mes es corto).
    Sin ajuste por fin de semana en v1."""
    if card.payment_due_days is not None:
        return period_end + timedelta(days=card.payment_due_days)
    if card.payment_day is None:
        raise ValueError("La tarjeta requiere payment_due_days o payment_day (TDC-01)")
    # Reusa la lógica de cortes: mismo dominio (1-28 o 'last') y mismo ajuste.
    spec = CardCycleSpec(statement_day=card.payment_day)
    return next_cutoff(period_end, spec)
