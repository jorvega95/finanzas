"""Pronóstico de flujo a futuro. Implementa PRO-01..PRO-06.

Proyección de flujo de caja **read-only**: nunca persiste nada ni materializa
statements (TDC-11). A diferencia del dashboard devengado (DSH-04), aquí importa
*cuándo* sale/entra el dinero. Recorre una línea de tiempo de eventos fechados
manteniendo un saldo líquido y marca el primer punto donde se vuelve negativo
(sobregiro, PRO-05). Todo en `date` puro (GLO-02) y `Decimal` (GLO-01).
"""

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.cards import Card, CardStatement, StatementStatus
from app.models.catalogs import CardBehavior, CardType, PaymentMethod
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus
from app.models.recurring import RecurringRule
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import billing_cycles as cycles
from app.services import fx
from app.services.cards import cycle_ready, spec_for
from app.services.recurring import occurrences

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def to_money(value: Decimal | int | None) -> Decimal:
    """GLO-01: 2 decimales, ROUND_HALF_EVEN."""
    return Decimal(value or 0).quantize(CENT, ROUND_HALF_EVEN)


def add_months(d: dt.date, months: int) -> dt.date:
    """Horizonte: suma `months` meses a `d` recortando el día al fin de mes."""
    import calendar

    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


@dataclass
class _Event:
    date: dt.date
    kind: str  # income | recurring_income | card_due | recurring_expense | manual_expense
    direction: str  # in | out
    description: str
    amount: Decimal  # base, magnitud positiva
    currency: str  # moneda original
    is_estimate: bool = False
    covered: bool = True
    shortfall: Decimal = ZERO
    balance_after: Decimal = ZERO


@dataclass
class _RateCache:
    """PRO-06: convierte a base con la última tasa disponible (no congelada)."""

    session: AsyncSession
    base: str
    on_date: dt.date
    _cache: dict[str, Decimal] = field(default_factory=dict)

    async def to_base(self, amount: Decimal, currency: str) -> Decimal:
        if currency == self.base:
            return Decimal(amount)
        if currency not in self._cache:
            rate = await fx.get_rate(self.session, currency, self.base, self.on_date)
            self._cache[currency] = Decimal(rate) if rate is not None else Decimal(1)
        return Decimal(amount) * self._cache[currency]


async def _credit_cards(session: AsyncSession, space_id: uuid.UUID) -> list[Card]:
    """TAR-01: tarjetas de behavior credit (incluye inactivas: TDC-12 siguen
    facturando hasta liquidar)."""
    return list(
        (
            await session.execute(
                select(Card)
                .join(CardType, Card.card_type_id == CardType.id)
                .where(Card.space_id == space_id, CardType.behavior == CardBehavior.credit)
            )
        )
        .scalars()
        .all()
    )


async def _credit_method_ids(
    session: AsyncSession, space_id: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    """Métodos de pago vinculados a tarjetas de crédito → {method_id: card_id}."""
    rows = (
        await session.execute(
            select(PaymentMethod.id, Card.id)
            .join(Card, PaymentMethod.card_id == Card.id)
            .join(CardType, Card.card_type_id == CardType.id)
            .where(
                PaymentMethod.space_id == space_id,
                CardType.behavior == CardBehavior.credit,
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _as_of_balance(
    session: AsyncSession, rates: _RateCache, space: Space, today: dt.date
) -> Decimal:
    """PRO-02: caja líquida a hoy = Σ saldos débito/prepago (TAR-05) hasta hoy.

    Réplica de cards.card_balance pero acotada a date <= hoy (el saldo actual,
    no el all-time que incluye cargos futuros). Convertida a base (PRO-06)."""
    cards = (
        (
            await session.execute(
                select(Card)
                .join(CardType, Card.card_type_id == CardType.id)
                .where(
                    Card.space_id == space.id,
                    Card.is_active.is_(True),
                    CardType.behavior.in_([CardBehavior.debit, CardBehavior.prepaid]),
                )
            )
        )
        .scalars()
        .all()
    )
    total = ZERO
    for card in cards:
        if card.payment_method_id is None:
            continue
        method_id = card.payment_method_id

        async def summed(*predicates: ColumnElement[bool]) -> Decimal:
            value = await session.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.space_id == space.id,
                    Transaction.date <= today,
                    *predicates,
                )
            )
            return Decimal(value or 0)

        income = await summed(
            Transaction.type == TransactionType.income,
            Transaction.payment_method_id == method_id,
        )
        transfer_in = await summed(
            Transaction.type == TransactionType.transfer,
            Transaction.payment_method_to_id == method_id,
        )
        expense = await summed(
            Transaction.type == TransactionType.expense,
            Transaction.payment_method_id == method_id,
            Transaction.installment_plan_id.is_(None),
        )
        transfer_out = await summed(
            Transaction.type == TransactionType.transfer,
            Transaction.payment_method_id == method_id,
        )
        initial = Decimal(card.initial_balance if card.initial_balance is not None else 0)
        balance = initial + income + transfer_in - expense - transfer_out
        total += await rates.to_base(balance, card.currency)
    return total


async def _projected_cutoffs(card: Card, today: dt.date, horizon_end: dt.date) -> list[dt.date]:
    """Cortes cuyo due_date cae dentro del horizonte (a partir del ciclo abierto)."""
    spec = spec_for(card)
    cutoffs: list[dt.date] = []
    cutoff = cycles.cutoff_on_or_after(today, spec)
    while cycles.due_date_for(cutoff, spec) <= horizon_end:
        cutoffs.append(cutoff)
        cutoff = cycles.next_cutoff(cutoff, spec)
    return cutoffs


def _bucket(item_cutoff: dt.date, projected: list[dt.date]) -> dt.date | None:
    """El primer corte proyectado >= item_cutoff (PRO-03: rezagados al primero)."""
    for c in projected:
        if c >= item_cutoff:
            return c
    return None


async def _card_due_events(
    session: AsyncSession,
    rates: _RateCache,
    card: Card,
    today: dt.date,
    horizon_end: dt.date,
) -> list[_Event]:
    """PRO-03: pagos de TDC. Statements cerrados reales + ciclos proyectados
    (cargos + cuotas MSI pending + domiciliados de crédito), fechados al due_date."""
    events: list[_Event] = []
    spec = spec_for(card)

    # Statements ya cerrados (closed/partially_paid/paid): su computed_total ya es
    # definitivo, así que sus transacciones/cuotas NUNCA deben re-proyectarse en un
    # corte futuro (de lo contrario un statement ya pagado se "recicla" y se suma
    # otra vez al próximo pago proyectado).
    settled = (
        (
            await session.execute(
                select(CardStatement).where(
                    CardStatement.credit_card_id == card.id,
                    CardStatement.status != StatementStatus.open,
                )
            )
        )
        .scalars()
        .all()
    )
    settled_ids = {s.id for s in settled}
    # (a) Statements cerrados/parciales no pagados (TDC-09a): saldo real.
    for s in settled:
        outstanding = s.computed_total - s.paid_amount
        if outstanding > ZERO:
            events.append(
                _Event(
                    date=max(s.due_date, today),
                    kind="card_due",
                    direction="out",
                    description=f"Pago {card.alias}",
                    amount=to_money(await rates.to_base(outstanding, card.currency)),
                    currency=card.currency,
                )
            )

    projected = await _projected_cutoffs(card, today, horizon_end)
    if not projected:
        return events

    # Acumulador por corte proyectado.
    by_cutoff: dict[dt.date, Decimal] = {c: ZERO for c in projected}

    # Cargos reales (no madre MSI) aún no liquidados en un statement cerrado.
    txns = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.card_id == card.id,
                    Transaction.installment_plan_id.is_(None),
                    Transaction.type.in_([TransactionType.expense, TransactionType.income]),
                )
            )
        )
        .scalars()
        .all()
    )
    for txn in txns:
        if txn.statement_id is not None and txn.statement_id in settled_ids:
            continue  # ya contabilizado en su statement cerrado real
        _, cutoff = cycles.cycle_for_purchase(txn.date, spec)
        target = _bucket(cutoff, projected)
        if target is None:
            continue
        signed = txn.amount if txn.type == TransactionType.expense else -txn.amount
        by_cutoff[target] += await rates.to_base(signed, card.currency)

    # Cuotas MSI por cobrar (MSI-04): pending + charged aún en statement abierto
    # (las charged en un statement cerrado ya van en su computed_total real).
    pending = (
        (
            await session.execute(
                select(Installment)
                .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
                .where(
                    InstallmentPlan.credit_card_id == card.id,
                    Installment.status.in_([InstallmentStatus.pending, InstallmentStatus.charged]),
                )
            )
        )
        .scalars()
        .all()
    )
    for inst in pending:
        if inst.statement_id is not None and inst.statement_id in settled_ids:
            continue
        target = _bucket(inst.estimated_charge_date, projected)
        if target is None:
            continue
        by_cutoff[target] += await rates.to_base(inst.amount, card.currency)

    # Domiciliados recurrentes de crédito sobre esta tarjeta (REC, PRO-03).
    rules = await _active_expense_rules(session, card.space_id)
    for rule, rule_card_id in rules:
        if rule_card_id != card.id:
            continue
        for occ in occurrences(rule, horizon_end):
            if occ <= today:
                continue  # ya generado como transacción real
            _, cutoff = cycles.cycle_for_purchase(occ, spec)
            target = _bucket(cutoff, projected)
            if target is None:
                continue
            by_cutoff[target] += await rates.to_base(rule.amount, rule.currency)

    # Resta pagos ya aplicados al statement abierto del corte (si existe).
    open_statements = {
        s.period_end: s
        for s in (
            await session.execute(
                select(CardStatement).where(
                    CardStatement.credit_card_id == card.id,
                    CardStatement.status == StatementStatus.open,
                )
            )
        )
        .scalars()
        .all()
    }
    for cutoff in projected:
        amount = by_cutoff[cutoff]
        existing = open_statements.get(cutoff)
        if existing is not None:
            amount -= await rates.to_base(existing.paid_amount, card.currency)
        amount = to_money(amount)
        if amount > ZERO:
            events.append(
                _Event(
                    date=cycles.due_date_for(cutoff, spec),
                    kind="card_due",
                    direction="out",
                    description=f"Pago {card.alias}",
                    amount=amount,
                    currency=card.currency,
                )
            )
    return events


async def _active_expense_rules(
    session: AsyncSession, space_id: uuid.UUID
) -> list[tuple[RecurringRule, uuid.UUID | None]]:
    """Reglas de gasto activas con el card_id (de crédito) de su método, si lo hay."""
    rules = (
        (
            await session.execute(
                select(RecurringRule).where(
                    RecurringRule.space_id == space_id,
                    RecurringRule.is_active.is_(True),
                    RecurringRule.type == TransactionType.expense,
                )
            )
        )
        .scalars()
        .all()
    )
    credit_methods = await _credit_method_ids(session, space_id)
    return [
        (rule, credit_methods.get(rule.payment_method_id) if rule.payment_method_id else None)
        for rule in rules
    ]


async def _income_events(
    session: AsyncSession,
    rates: _RateCache,
    space_id: uuid.UUID,
    today: dt.date,
    horizon_end: dt.date,
) -> list[_Event]:
    """PRO-04: ingresos recurrentes (nómina) + ingresos futuros manuales."""
    events: list[_Event] = []
    rules = (
        (
            await session.execute(
                select(RecurringRule).where(
                    RecurringRule.space_id == space_id,
                    RecurringRule.is_active.is_(True),
                    RecurringRule.type == TransactionType.income,
                )
            )
        )
        .scalars()
        .all()
    )
    for rule in rules:
        for occ in occurrences(rule, horizon_end):
            if occ <= today:
                continue
            events.append(
                _Event(
                    date=occ,
                    kind="recurring_income",
                    direction="in",
                    description=rule.description,
                    amount=to_money(await rates.to_base(rule.amount, rule.currency)),
                    currency=rule.currency,
                    is_estimate=rule.amount_is_estimate,
                )
            )

    future = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.space_id == space_id,
                    Transaction.type == TransactionType.income,
                    Transaction.date > today,
                    Transaction.date <= horizon_end,
                    Transaction.recurring_rule_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for txn in future:
        events.append(
            _Event(
                date=txn.date,
                kind="income",
                direction="in",
                description=txn.description or "Ingreso",
                amount=to_money(await rates.to_base(txn.amount, txn.currency)),
                currency=txn.currency,
            )
        )
    return events


async def _non_credit_expense_events(
    session: AsyncSession,
    rates: _RateCache,
    space_id: uuid.UUID,
    today: dt.date,
    horizon_end: dt.date,
) -> list[_Event]:
    """PRO-03/TAR-04: salidas inmediatas (efectivo/débito/prepago): domiciliados
    no-crédito + gastos futuros manuales sin statement."""
    events: list[_Event] = []
    for rule, rule_card_id in await _active_expense_rules(session, space_id):
        if rule_card_id is not None:
            continue  # crédito: va al statement proyectado, no es flujo inmediato
        for occ in occurrences(rule, horizon_end):
            if occ <= today:
                continue
            events.append(
                _Event(
                    date=occ,
                    kind="recurring_expense",
                    direction="out",
                    description=rule.description,
                    amount=to_money(await rates.to_base(rule.amount, rule.currency)),
                    currency=rule.currency,
                    is_estimate=rule.amount_is_estimate,
                )
            )

    future = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.space_id == space_id,
                    Transaction.type == TransactionType.expense,
                    Transaction.date > today,
                    Transaction.date <= horizon_end,
                    Transaction.statement_id.is_(None),  # crédito siempre lleva statement
                    Transaction.installment_plan_id.is_(None),  # madre MSI excluida
                    Transaction.recurring_rule_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for txn in future:
        events.append(
            _Event(
                date=txn.date,
                kind="manual_expense",
                direction="out",
                description=txn.description or "Gasto",
                amount=to_money(await rates.to_base(txn.amount, txn.currency)),
                currency=txn.currency,
            )
        )
    return events


async def forecast(
    session: AsyncSession,
    space: Space,
    *,
    horizon_months: int = 6,
    cash_adjustment: Decimal = ZERO,
) -> dict[str, Any]:
    """PRO-01..06: construye el pronóstico de flujo. Read-only (no commit)."""
    today = today_in_tz(space.timezone)
    horizon_end = add_months(today, horizon_months)
    rates = _RateCache(session, space.base_currency, today)

    starting_cash = to_money(await _as_of_balance(session, rates, space, today) + cash_adjustment)

    events: list[_Event] = []
    events += await _income_events(session, rates, space.id, today, horizon_end)
    events += await _non_credit_expense_events(session, rates, space.id, today, horizon_end)
    for card in await _credit_cards(session, space.id):
        if not cycle_ready(card):
            continue  # TDC-15: sin día de corte no se proyectan ciclos
        events += await _card_due_events(session, rates, card, today, horizon_end)

    # PRO-05: recorre la línea de tiempo. Empates: entradas antes que salidas.
    events.sort(key=lambda e: (e.date, 0 if e.direction == "in" else 1))

    running = starting_cash
    min_balance = starting_cash
    min_balance_date: dt.date | None = today
    first_overdraft: dt.date | None = None
    total_shortfall = ZERO
    alerts: list[dict[str, Any]] = []

    for ev in events:
        running += ev.amount if ev.direction == "in" else -ev.amount
        ev.balance_after = running
        if ev.direction == "out" and running < ZERO:
            ev.covered = False
            ev.shortfall = min(ev.amount, -running)
            total_shortfall += ev.shortfall
            if first_overdraft is None:
                first_overdraft = ev.date
            alerts.append(
                {"date": ev.date, "description": ev.description, "shortfall": ev.shortfall}
            )
        if running < min_balance:
            min_balance = running
            min_balance_date = ev.date

    return {
        "horizon_months": horizon_months,
        "generated_for": today,
        "starting_cash": starting_cash,
        "cash_adjustment": to_money(cash_adjustment),
        "ending_balance": to_money(running),
        "min_balance": to_money(min_balance),
        "min_balance_date": min_balance_date,
        "first_overdraft_date": first_overdraft,
        "total_shortfall": to_money(total_shortfall),
        "events": [
            {
                "date": e.date,
                "kind": e.kind,
                "direction": e.direction,
                "description": e.description,
                "amount": e.amount,
                "currency": e.currency,
                "is_estimate": e.is_estimate,
                "covered": e.covered,
                "shortfall": to_money(e.shortfall),
                "balance_after": to_money(e.balance_after),
            }
            for e in events
        ],
        "alerts": alerts,
    }
