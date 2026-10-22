"""Monthly RESICO declarations. Implements FAC-06 (per period), FAC-07,
FAC-08, FAC-12 and FAC-13.

A fiscal period is the month of the payments (FAC-02). Its pesos are the sum
of each payment's pesos (rounded HALF_EVEN per payment, FAC-06) rounded to
whole pesos. That sum runs here, not in SQL: Postgres ROUND is half-up, and
FAC-06 requires HALF_EVEN on each row. Status is computed, never stored.
"""

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.core.text import normalize_name
from app.models.billing import FilingKind, TaxFiling
from app.models.catalogs import Category, CategoryKind, ExpenseNature
from app.models.spaces import Space
from app.models.transactions import TransactionType
from app.services import billing
from app.services.billing import STATUS_EXCLUDED, STATUS_PENDING, PaymentState, fiscal_mxn
from app.services.files import get_file

PESO = Decimal("1")
ZERO = Decimal("0.00")
TAXES_CATEGORY_NAME = "Impuestos"  # FAC-13
# FAC-07: monthly RESICO table for individuals (LISR 113-E), upper bound → rate.
RESICO_MONTHLY: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("25000.00"), Decimal("0.0100")),
    (Decimal("50000.00"), Decimal("0.0110")),
    (Decimal("83333.33"), Decimal("0.0150")),
    (Decimal("208333.33"), Decimal("0.0200")),
    (Decimal("291666.67"), Decimal("0.0250")),
)
RESICO_MAX_RATE = Decimal("0.0250")
MONTHS_ES = billing.MONTHS_ES

PERIOD_OPEN = "open"  # the month is still running
PERIOD_TO_DECLARE = "to_declare"
PERIOD_TO_PAY = "to_pay"
PERIOD_PAID = "paid"


def _reject(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


# --- Pure helpers (FAC-06/07/12) -------------------------------------------------------


def to_pesos(value: Decimal) -> Decimal:
    """FAC-06: the SAT declares whole pesos."""
    return value.quantize(PESO, rounding=ROUND_HALF_EVEN)


def resico_rate(monthly_income: Decimal) -> Decimal:
    for upper, rate in RESICO_MONTHLY:
        if monthly_income <= upper:
            return rate
    return RESICO_MAX_RATE


def isr_estimate(monthly_income: Decimal) -> tuple[Decimal, Decimal]:
    """FAC-07: (rate, ISR in whole pesos). An estimate: the acuse rules."""
    rate = resico_rate(monthly_income)
    return rate, to_pesos(monthly_income * rate)


def _nth_monday(year: int, month: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))


def mexican_holidays(year: int) -> set[dt.date]:
    """Mandatory rest days (LFT art. 74) that move a SAT deadline."""
    days = {
        dt.date(year, 1, 1),
        _nth_monday(year, 2, 1),
        _nth_monday(year, 3, 3),
        dt.date(year, 5, 1),
        dt.date(year, 9, 16),
        _nth_monday(year, 11, 3),
        dt.date(year, 12, 25),
    }
    if (year - 2024) % 6 == 0:
        days.add(dt.date(year, 10, 1))  # change of federal executive
    return days


def is_business_day(day: dt.date) -> bool:
    return day.weekday() < 5 and day not in mexican_holidays(day.year)


def next_business_day(day: dt.date) -> dt.date:
    while not is_business_day(day):
        day += dt.timedelta(days=1)
    return day


def add_business_days(day: dt.date, count: int) -> dt.date:
    for _ in range(count):
        day = next_business_day(day + dt.timedelta(days=1))
    return day


def filing_deadline(period_start: dt.date, extra_days: int) -> dt.date:
    """FAC-12: the 17th of the next month (moved to the next business day)
    plus the business days granted by the RFC's sixth digit."""
    base = next_business_day(period_start + relativedelta(months=1, day=17))
    return add_business_days(base, extra_days)


def month_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    start = day.replace(day=1)
    return start, start + relativedelta(months=1, days=-1)


def month_es(period: dt.date) -> str:
    return f"{MONTHS_ES[period.month - 1]} {period.year}"


# --- Period state (FAC-06/07/08/12) ----------------------------------------------------


@dataclass
class PrefillItem:
    """FAC-08: an invoice whose issue month differs from its payment month."""

    payment_id: uuid.UUID
    payment_date: dt.date
    issue_date: dt.date
    mxn: Decimal | None


@dataclass
class PeriodState:
    period: dt.date
    payments: list[PaymentState] = field(default_factory=list)
    filings: list[TaxFiling] = field(default_factory=list)
    to_declare_exact: Decimal = ZERO  # Σ pesos of the payments (cents)
    missing_rates: int = 0
    pending_invoice: int = 0
    sat_prefill_exact: Decimal = ZERO  # Σ pesos of invoices issued this month
    prefill_unknown: int = 0
    exclude_from_prefill: list[PrefillItem] = field(default_factory=list)
    add_to_prefill: list[PrefillItem] = field(default_factory=list)
    status: str = PERIOD_OPEN
    deadline: dt.date = dt.date.min
    payment_deadline: dt.date | None = None
    is_overdue: bool = False

    @property
    def to_declare(self) -> Decimal:
        return to_pesos(self.to_declare_exact)

    @property
    def sat_prefill(self) -> Decimal:
        return to_pesos(self.sat_prefill_exact)

    @property
    def isr_rate(self) -> Decimal:
        return isr_estimate(self.to_declare)[0]

    @property
    def isr_estimate(self) -> Decimal:
        return isr_estimate(self.to_declare)[1]

    @property
    def amount_due(self) -> Decimal:
        return sum((f.amount_due for f in self.filings), ZERO)

    @property
    def unpaid(self) -> list[TaxFiling]:
        return [f for f in self.filings if f.amount_due > ZERO and f.paid_date is None]


def _invoice_mxn(state: PaymentState) -> Decimal | None:
    inv = state.invoice
    if inv is None:
        return None
    return fiscal_mxn(inv.total, inv.currency, inv.fx_rate or state.payment.fiscal_fx_rate)


async def list_filings(session: AsyncSession, space_id: uuid.UUID) -> list[TaxFiling]:
    rows = await session.scalars(
        select(TaxFiling)
        .where(TaxFiling.space_id == space_id)
        .order_by(TaxFiling.period_start, TaxFiling.filed_date, TaxFiling.created_at)
    )
    return list(rows.all())


async def extra_days(session: AsyncSession, space_id: uuid.UUID) -> int:
    settings_row = await billing.get_settings(session, space_id)
    return settings_row.rfc_extra_days if settings_row else 0


async def list_periods(session: AsyncSession, space: Space) -> list[PeriodState]:
    """Every month with payments, invoices or filings, newest first."""
    today = today_in_tz(space.timezone)
    current = today.replace(day=1)
    extra = await extra_days(session, space.id)
    periods: dict[dt.date, PeriodState] = {}

    def period(day: dt.date) -> PeriodState:
        key = day.replace(day=1)
        if key not in periods:
            periods[key] = PeriodState(period=key)
        return periods[key]

    for state in await billing.list_payments(session, space.id):
        if state.status == STATUS_EXCLUDED:
            continue
        own = period(state.payment.payment_date)
        own.payments.append(state)
        mxn = state.mxn
        if mxn is None:
            own.missing_rates += 1
        else:
            own.to_declare_exact += mxn
        if state.status == STATUS_PENDING:
            own.pending_invoice += 1
        inv = state.invoice
        if inv is None:
            continue
        issued = period(inv.issue_date)
        inv_mxn = _invoice_mxn(state)
        if inv_mxn is None:
            issued.prefill_unknown += 1
        else:
            issued.sat_prefill_exact += inv_mxn
        if issued is not own:
            item = PrefillItem(
                state.payment.id, state.payment.payment_date, inv.issue_date, inv_mxn
            )
            issued.exclude_from_prefill.append(item)
            own.add_to_prefill.append(item)

    for filing in await list_filings(session, space.id):
        period(filing.period_start).filings.append(filing)

    for ps in periods.values():
        ps.deadline = filing_deadline(ps.period, extra)
        unpaid = ps.unpaid
        if ps.period >= current:
            ps.status = PERIOD_OPEN
        elif not ps.filings:
            ps.status = PERIOD_TO_DECLARE
        elif unpaid:
            ps.status = PERIOD_TO_PAY
            valid = [f.valid_until for f in unpaid if f.valid_until is not None]
            ps.payment_deadline = min(valid) if valid else ps.deadline
        else:
            ps.status = PERIOD_PAID
        limit = ps.payment_deadline or ps.deadline
        ps.is_overdue = ps.status in (PERIOD_TO_DECLARE, PERIOD_TO_PAY) and today > limit
    return sorted(periods.values(), key=lambda s: s.period, reverse=True)


# --- Filings (FAC-12) -----------------------------------------------------------------


async def get_filing(session: AsyncSession, space_id: uuid.UUID, filing_id: uuid.UUID) -> TaxFiling:
    filing: TaxFiling | None = await session.scalar(
        select(TaxFiling).where(TaxFiling.id == filing_id, TaxFiling.space_id == space_id)
    )
    if filing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Declaración no encontrada")
    return filing


async def _check_normal_unique(
    session: AsyncSession, space_id: uuid.UUID, period: dt.date, exclude: uuid.UUID | None
) -> None:
    stmt = select(TaxFiling.id).where(
        TaxFiling.space_id == space_id,
        TaxFiling.period_start == period,
        TaxFiling.kind == FilingKind.normal,
    )
    if exclude is not None:
        stmt = stmt.where(TaxFiling.id != exclude)
    if await session.scalar(stmt) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ese mes ya tiene declaración normal; registra una complementaria",
        )


async def _validate_filing(
    session: AsyncSession, space: Space, data: dict[str, Any], current: TaxFiling | None
) -> None:
    today = today_in_tz(space.timezone)
    if "period" in data:
        start, end = month_bounds(data.pop("period"))
        if start >= today.replace(day=1):
            raise _reject("El mes aún no termina: se declara a partir del día 1 del siguiente")
        data["period_start"], data["period_end"] = start, end
    if data.get("filed_date") is not None and data["filed_date"] > today:
        raise _reject("La fecha de presentación no puede ser futura")
    period_start = data.get("period_start", current.period_start if current else None)
    kind = data.get("kind", current.kind if current else FilingKind.normal)
    if period_start is not None and kind == FilingKind.normal:
        await _check_normal_unique(session, space.id, period_start, current.id if current else None)
    if data.get("ack_file_id") is not None:
        await get_file(session, space.id, data["ack_file_id"])  # GLO-05


async def create_filing(
    session: AsyncSession, space: Space, created_by: uuid.UUID, data: dict[str, Any]
) -> TaxFiling:
    """FAC-12: the acuse of a month (normal, or a complementary one)."""
    payment = data.pop("payment", None)
    await _validate_filing(session, space, data, None)
    filing = TaxFiling(space_id=space.id, created_by=created_by, **data)
    session.add(filing)
    await session.flush()
    if payment is not None:
        await _apply_payment(session, space, created_by, filing, payment)
    await session.commit()
    await session.refresh(filing)
    return filing


async def update_filing(
    session: AsyncSession, space: Space, filing: TaxFiling, changes: dict[str, Any]
) -> TaxFiling:
    await _validate_filing(session, space, changes, filing)
    if (
        "amount_due" in changes
        and filing.paid_date is not None
        and changes["amount_due"] != filing.amount_due
        and changes["amount_due"] == ZERO
    ):
        raise _reject("Esta declaración ya tiene pago; quítalo antes de dejarla en ceros")
    for key, value in changes.items():
        setattr(filing, key, value)
    await session.commit()
    await session.refresh(filing)
    return filing


async def delete_filing(session: AsyncSession, filing: TaxFiling) -> None:
    if filing.paid_date is not None:
        raise _reject("Esta declaración ya tiene pago; quítalo antes de borrarla")
    await session.delete(filing)
    await session.commit()


# --- Payment and the "Impuestos" expense (FAC-12/13) -----------------------------------


async def ensure_taxes_category(
    session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID
) -> Category:
    """FAC-13: "Impuestos", seeded with the first tax payment (CAT-01)."""
    normalized = normalize_name(TAXES_CATEGORY_NAME)
    category: Category | None = await session.scalar(
        select(Category).where(
            Category.space_id == space_id,
            Category.kind == CategoryKind.expense,
            Category.name_normalized == normalized,
        )
    )
    if category is None:
        category = Category(
            space_id=space_id,
            name=TAXES_CATEGORY_NAME,
            name_normalized=normalized,
            kind=CategoryKind.expense,
            expense_nature=ExpenseNature.fixed,
            created_by=created_by,
        )
        session.add(category)
        await session.flush()
    elif not category.is_active:
        raise _reject('La categoría "Impuestos" está desactivada; reactívala en Catálogos')
    return category


async def _drop_expense(session: AsyncSession, space: Space, filing: TaxFiling) -> None:
    """FAC-13: removing the payment removes its expense (same unit of work)."""
    from app.services.transactions import delete_transaction

    txn_id = filing.expense_transaction_id
    if txn_id is None:
        return
    filing.expense_transaction_id = None
    await session.flush()
    await delete_transaction(session, space.id, txn_id, commit=False)


async def _apply_payment(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    filing: TaxFiling,
    data: dict[str, Any],
) -> None:
    from app.services.transactions import TransactionInput, create_transaction

    today = today_in_tz(space.timezone)
    if data["paid_date"] > today:
        raise _reject("La fecha de pago no puede ser futura")
    if data["paid_date"] < filing.filed_date:
        raise _reject("El pago no puede ser anterior a la presentación de la declaración")
    if data.get("receipt_file_id") is not None:
        await get_file(session, space.id, data["receipt_file_id"])
    await _drop_expense(session, space, filing)
    filing.paid_date = data["paid_date"]
    filing.paid_amount = data["paid_amount"]
    filing.receipt_file_id = data.get("receipt_file_id")
    account_id = data.get("account_id")
    if account_id is not None:
        category = await ensure_taxes_category(session, space.id, created_by)
        txn = await create_transaction(
            session,
            space,
            created_by,
            TransactionInput(
                type=TransactionType.expense,
                date=data["paid_date"],
                amount=data["paid_amount"],
                currency="MXN",
                account_id=account_id,
                category_id=category.id,
                description=f"Impuestos RESICO {month_es(filing.period_start)}",
            ),
            commit=False,
        )
        filing.expense_transaction_id = txn.id
    await session.flush()


async def set_payment(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    filing: TaxFiling,
    data: dict[str, Any],
) -> TaxFiling:
    """FAC-12/13: register (or replace) the payment of the capture line."""
    await _apply_payment(session, space, created_by, filing, data)
    await session.commit()
    await session.refresh(filing)
    return filing


async def remove_payment(session: AsyncSession, space: Space, filing: TaxFiling) -> TaxFiling:
    if filing.paid_date is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La declaración no tiene pago")
    await _drop_expense(session, space, filing)
    filing.paid_date = None
    filing.paid_amount = None
    filing.receipt_file_id = None
    await session.commit()
    await session.refresh(filing)
    return filing
