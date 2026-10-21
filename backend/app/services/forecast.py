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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.accounts import Account, Statement, StatementStatus
from app.models.catalogs import AccountBehavior, AccountType
from app.models.msi import Installment, InstallmentPlan, InstallmentStatus
from app.models.recurring import RecurringKind, RecurringRule
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services import billing_cycles as cycles
from app.services import fx
from app.services.accounts import account_balance, cycle_ready, spec_for
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
    # | loan_in | loan_out (TAR-11) | savings_in | savings_out (PRO-07)
    # | commitment (CXP-07)
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


async def _credit_cards(session: AsyncSession, space_id: uuid.UUID) -> list[Account]:
    """TAR-01: tarjetas de behavior credit (incluye inactivas: TDC-12 siguen
    facturando hasta liquidar)."""
    return list(
        (
            await session.execute(
                select(Account)
                .join(AccountType, Account.account_type_id == AccountType.id)
                .where(Account.space_id == space_id, AccountType.behavior == AccountBehavior.credit)
            )
        )
        .scalars()
        .all()
    )


async def _credit_account_ids(session: AsyncSession, space_id: uuid.UUID) -> set[uuid.UUID]:
    """Ids de las cuentas de crédito del espacio (TAR-01)."""
    rows = await session.execute(
        select(Account.id)
        .join(AccountType, Account.account_type_id == AccountType.id)
        .where(Account.space_id == space_id, AccountType.behavior == AccountBehavior.credit)
    )
    return set(rows.scalars().all())


# PRO-02: cuentas líquidas; el ahorro, los préstamos y las inversiones no entran a la caja.
LIQUID_BEHAVIORS = (AccountBehavior.debit, AccountBehavior.prepaid, AccountBehavior.cash)


@dataclass
class _Perimeter:
    """PRO-07/08: qué cuentas son "el dinero disponible" en este pronóstico.

    liquid   cuentas cuya caja se proyecta (efectivo/débito/prepago, y ahorro
             si `include_savings`).
    outside  cuentas con saldo fuera del perímetro (préstamos siempre; ahorro
             si no se incluye): lo que pasa dentro de ellas no es flujo, y una
             transferencia que cruza la frontera sí lo es.
    """

    liquid_behaviors: tuple[AccountBehavior, ...]
    liquid: set[uuid.UUID]
    outside: set[uuid.UUID]
    savings: set[uuid.UUID]


async def _perimeter(
    session: AsyncSession, space_id: uuid.UUID, include_savings: bool
) -> _Perimeter:
    behaviors = LIQUID_BEHAVIORS + ((AccountBehavior.savings,) if include_savings else ())
    outside_behaviors: tuple[AccountBehavior, ...] = (AccountBehavior.loan,) + (
        () if include_savings else (AccountBehavior.savings,)
    )
    return _Perimeter(
        liquid_behaviors=behaviors,
        liquid=await _account_ids(session, space_id, behaviors),
        outside=await _account_ids(session, space_id, outside_behaviors),
        savings=await _account_ids(session, space_id, (AccountBehavior.savings,)),
    )


async def _account_ids(
    session: AsyncSession, space_id: uuid.UUID, behaviors: tuple[AccountBehavior, ...]
) -> set[uuid.UUID]:
    rows = await session.execute(
        select(Account.id)
        .join(AccountType, Account.account_type_id == AccountType.id)
        .where(Account.space_id == space_id, AccountType.behavior.in_(behaviors))
    )
    return set(rows.scalars().all())


async def _as_of_balance(
    session: AsyncSession,
    rates: _RateCache,
    space: Space,
    today: dt.date,
    behaviors: tuple[AccountBehavior, ...] = LIQUID_BEHAVIORS,
) -> Decimal:
    """PRO-02: caja líquida a hoy = Σ saldos (TAR-05) de las cuentas activas
    del perímetro (PRO-07/08), acotados a date <= hoy (el saldo actual, no el
    all-time que incluye movimientos futuros). Convertida a base (PRO-06)."""
    accounts = (
        (
            await session.execute(
                select(Account)
                .join(AccountType, Account.account_type_id == AccountType.id)
                .where(
                    Account.space_id == space.id,
                    Account.is_active.is_(True),
                    AccountType.behavior.in_(behaviors),
                )
            )
        )
        .scalars()
        .all()
    )
    total = ZERO
    for account in accounts:
        balance = await account_balance(session, account, as_of=today)
        total += await rates.to_base(balance, account.currency)
    return total


async def _projected_cutoffs(
    account: Account, today: dt.date, horizon_end: dt.date
) -> list[dt.date]:
    """Cortes cuyo due_date cae dentro del horizonte (a partir del ciclo abierto)."""
    spec = spec_for(account)
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
    account: Account,
    today: dt.date,
    horizon_end: dt.date,
) -> list[_Event]:
    """PRO-03: pagos de TDC. Statements cerrados reales + ciclos proyectados
    (cargos + cuotas MSI pending + domiciliados de crédito), fechados al due_date."""
    events: list[_Event] = []
    spec = spec_for(account)

    # Statements ya cerrados (closed/partially_paid/paid): su computed_total ya es
    # definitivo, así que sus transacciones/cuotas NUNCA deben re-proyectarse en un
    # corte futuro (de lo contrario un statement ya pagado se "recicla" y se suma
    # otra vez al próximo pago proyectado).
    settled = (
        (
            await session.execute(
                select(Statement).where(
                    Statement.account_id == account.id,
                    Statement.status != StatementStatus.open,
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
                    description=f"Pago {account.name}",
                    amount=to_money(await rates.to_base(outstanding, account.currency)),
                    currency=account.currency,
                )
            )

    projected = await _projected_cutoffs(account, today, horizon_end)
    if not projected:
        return events

    # Acumulador por corte proyectado.
    by_cutoff: dict[dt.date, Decimal] = {c: ZERO for c in projected}

    # Cargos reales (no madre MSI) aún no liquidados en un statement cerrado.
    txns = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.account_id == account.id,
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
        by_cutoff[target] += await rates.to_base(signed, account.currency)

    # Cuotas MSI por cobrar (MSI-04): pending + charged aún en statement abierto
    # (las charged en un statement cerrado ya van en su computed_total real).
    pending = (
        (
            await session.execute(
                select(Installment)
                .join(InstallmentPlan, Installment.plan_id == InstallmentPlan.id)
                .where(
                    InstallmentPlan.account_id == account.id,
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
        by_cutoff[target] += await rates.to_base(inst.amount, account.currency)

    # Domiciliados recurrentes de crédito sobre esta tarjeta (REC, PRO-03).
    rules = await _active_expense_rules(session, account.space_id)
    for rule, rule_credit_id in rules:
        if rule_credit_id != account.id or rule.amount is None:
            continue  # PRO-04: a bill without estimate is not projected
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
                select(Statement).where(
                    Statement.account_id == account.id,
                    Statement.status == StatementStatus.open,
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
            amount -= await rates.to_base(existing.paid_amount, account.currency)
        amount = to_money(amount)
        if amount > ZERO:
            events.append(
                _Event(
                    date=cycles.due_date_for(cutoff, spec),
                    kind="card_due",
                    direction="out",
                    description=f"Pago {account.name}",
                    amount=amount,
                    currency=account.currency,
                )
            )
    return events


async def _active_expense_rules(
    session: AsyncSession, space_id: uuid.UUID
) -> list[tuple[RecurringRule, uuid.UUID | None]]:
    """Reglas de gasto activas con el account_id de su cuenta si es de crédito."""
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
    credit_ids = await _credit_account_ids(session, space_id)
    return [(rule, rule.account_id if rule.account_id in credit_ids else None) for rule in rules]


async def _income_events(
    session: AsyncSession,
    rates: _RateCache,
    space_id: uuid.UUID,
    today: dt.date,
    horizon_end: dt.date,
    outside: set[uuid.UUID],
) -> list[_Event]:
    """PRO-04: ingresos recurrentes (nómina) + ingresos futuros manuales.
    Un ingreso en una cuenta fuera del perímetro (PRO-07: préstamo, o ahorro
    si no se incluye) no es flujo de caja."""
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
        if rule.account_id in outside or rule.amount is None:
            continue
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
                    # PEND-02: un income ya asignado a un statement de TDC (TDC-16)
                    # ya se cuenta vía _card_due_events; no duplicarlo aquí.
                    Transaction.statement_id.is_(None),
                    Transaction.recurring_rule_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for txn in future:
        if txn.account_id in outside:
            continue
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
    outside: set[uuid.UUID],
) -> list[_Event]:
    """PRO-03/TAR-04: salidas inmediatas (efectivo/débito/prepago): domiciliados
    no-crédito + gastos futuros manuales sin statement. Un gasto en una cuenta
    fuera del perímetro (PRO-07: lo que paga el acreedor de un préstamo, o un
    gasto desde el ahorro si no se incluye) no sale de tu caja."""
    events: list[_Event] = []
    for rule, rule_credit_id in await _active_expense_rules(session, space_id):
        if rule_credit_id is not None:
            continue  # crédito: va al statement proyectado, no es flujo inmediato
        if rule.account_id in outside or rule.amount is None:
            continue  # PRO-04: a bill without estimate is not projected
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
                    is_estimate=rule.amount_is_estimate or rule.kind == RecurringKind.bill,
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
        if txn.account_id in outside:
            continue
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


async def _boundary_transfer_events(
    session: AsyncSession,
    rates: _RateCache,
    space_id: uuid.UUID,
    today: dt.date,
    horizon_end: dt.date,
    perimeter: _Perimeter,
) -> list[_Event]:
    """PRO-07/TAR-11: transferencias futuras que cruzan la frontera del
    perímetro. Salir hacia un préstamo (abono) o hacia el ahorro no incluido
    (apartar) es salida; volver de ellos es entrada, por el monto recibido
    (TXN-13). Entre cuentas del mismo lado no hay flujo."""
    if not perimeter.outside:
        return []
    liquid_ids, outside = perimeter.liquid, perimeter.outside
    future = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.space_id == space_id,
                    Transaction.type == TransactionType.transfer,
                    Transaction.date > today,
                    Transaction.date <= horizon_end,
                )
            )
        )
        .scalars()
        .all()
    )
    events: list[_Event] = []
    for txn in future:
        if txn.account_id in liquid_ids and txn.account_to_id in outside:
            to_savings = txn.account_to_id in perimeter.savings
            amount, currency, direction = txn.amount, txn.currency, "out"
            kind = "savings_out" if to_savings else "loan_out"
            label = "Apartado a ahorro" if to_savings else "Abono a préstamo"
        elif txn.account_id in outside and txn.account_to_id in liquid_ids:
            from_savings = txn.account_id in perimeter.savings
            received = txn.amount_to if txn.amount_to is not None else txn.amount
            target = await session.get(Account, txn.account_to_id)
            currency = target.currency if target is not None else txn.currency
            amount, direction = received, "in"
            kind = "savings_in" if from_savings else "loan_in"
            label = "Retiro de ahorro" if from_savings else "Préstamo recibido"
        else:
            continue
        events.append(
            _Event(
                date=txn.date,
                kind=kind,
                direction=direction,
                description=txn.description or label,
                amount=to_money(await rates.to_base(amount, currency)),
                currency=currency,
            )
        )
    return events


async def _commitment_events(
    session: AsyncSession,
    rates: _RateCache,
    space: Space,
    today: dt.date,
    horizon_end: dt.date,
) -> tuple[list[_Event], list[dict[str, Any]]]:
    """CXP-07: what is still owed to vendors. Uncovered schedule rows on their
    date (overdue ones today); the unscheduled pending on `due_date`; without
    any date it is reported apart and doesn't enter the series. Future abonos
    already captured count as paid, so nothing is projected twice."""
    from app.services.commitments import pending_obligations

    events: list[_Event] = []
    undated: list[dict[str, Any]] = []
    for item in await pending_obligations(session, space):
        amount = to_money(await rates.to_base(item.amount, item.commitment.currency))
        if item.due_date is None:
            undated.append(
                {
                    "description": item.commitment.name,
                    "amount": amount,
                    "currency": item.commitment.currency,
                }
            )
            continue
        when = max(item.due_date, today)
        if when > horizon_end:
            continue
        events.append(
            _Event(
                date=when,
                kind="commitment",
                direction="out",
                description=f"Pago a {item.commitment.name}",
                amount=amount,
                currency=item.commitment.currency,
            )
        )
    return events, undated


async def forecast(
    session: AsyncSession,
    space: Space,
    *,
    horizon_months: int = 6,
    cash_adjustment: Decimal = ZERO,
    include_savings: bool = False,
) -> dict[str, Any]:
    """PRO-01..08: construye el pronóstico de flujo. Read-only (no commit).
    `include_savings` (PRO-08) mete el ahorro al perímetro de liquidez."""
    today = today_in_tz(space.timezone)
    horizon_end = add_months(today, horizon_months)
    rates = _RateCache(session, space.base_currency, today)
    perimeter = await _perimeter(session, space.id, include_savings)

    savings_included = (
        to_money(await _as_of_balance(session, rates, space, today, (AccountBehavior.savings,)))
        if include_savings
        else ZERO
    )
    starting_cash = to_money(
        await _as_of_balance(session, rates, space, today, perimeter.liquid_behaviors)
        + cash_adjustment
    )

    events: list[_Event] = []
    events += await _income_events(session, rates, space.id, today, horizon_end, perimeter.outside)
    events += await _non_credit_expense_events(
        session, rates, space.id, today, horizon_end, perimeter.outside
    )
    events += await _boundary_transfer_events(
        session, rates, space.id, today, horizon_end, perimeter
    )
    commitment_events, undated_commitments = await _commitment_events(
        session, rates, space, today, horizon_end
    )
    events += commitment_events
    for account in await _credit_cards(session, space.id):
        if not cycle_ready(account):
            continue  # TDC-15: sin día de corte no se proyectan ciclos
        events += await _card_due_events(session, rates, account, today, horizon_end)

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
        "undated_commitments": undated_commitments,  # CXP-07
        "include_savings": include_savings,  # PRO-08
        "savings_included": savings_included,  # PRO-08: parte del saldo inicial
    }
