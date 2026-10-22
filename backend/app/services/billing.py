"""Invoicing of freelance income (RESICO). Implements FAC-01..FAC-06 (per
payment), FAC-10, FAC-11 and FAC-14.

status = excluded | pending_invoice | invoiced, computed in SQL from the
payment and its invoice (FAC-04), never stored. GLO-01: Decimal everywhere.
GLO-02: pure dates. GLO-05: space-scoped (another space's ids are 404).
"""

import datetime as dt
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import today_in_tz
from app.models.accounts import Account
from app.models.billing import (
    BillingClient,
    BillingSettings,
    Invoice,
    InvoiceablePayment,
    StoredFile,
    TaxFiling,
)
from app.models.spaces import Space
from app.models.transactions import Transaction, TransactionType
from app.services.files import get_file

SUPPORTED_CURRENCIES = {"MXN", "USD"}  # TXN-04
CENT = Decimal("0.01")
SAT_URL_FIELDS = ("sat_invoice_url", "sat_filing_url", "sat_payment_url")
DEFAULT_CONCEPT_TEMPLATE = (
    "Servicios de entrenamiento y evaluación de modelos de IA periodo {periodo} "
    "pago recibido el {fecha_pago}"
)
MISSING_PERIOD = "[periodo trabajado]"
# FAC-11: XTRM describes a payment as "Payment for 2026-09-21 to 2026-09-27".
_XTRM_PERIOD = re.compile(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

STATUS_EXCLUDED = "excluded"
STATUS_PENDING = "pending_invoice"
STATUS_INVOICED = "invoiced"
STATUS_DECLARED = "declared"  # FAC-04/12: its period has an unpaid acuse
STATUS_PAID = "paid"  # FAC-04/12: every acuse of its period is settled
STATUSES = (STATUS_PENDING, STATUS_INVOICED, STATUS_DECLARED, STATUS_PAID, STATUS_EXCLUDED)


def _reject(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} no encontrado")


# --- Pure helpers (FAC-02/06/11) -----------------------------------------------------


def fiscal_period(payment_date: dt.date) -> dt.date:
    """FAC-02: the period is the month the money landed in the wallet."""
    return payment_date.replace(day=1)


def fiscal_mxn(amount: Decimal, currency: str, rate: Decimal | None) -> Decimal | None:
    """FAC-06: pesos of one payment (centavos, HALF_EVEN); None without a rate."""
    if currency == "MXN":
        return amount
    if rate is None:
        return None
    return (amount * rate).quantize(CENT, rounding=ROUND_HALF_EVEN)


def parse_work_period(text: str) -> tuple[dt.date, dt.date] | None:
    """FAC-11: work period from an XTRM description, if present and valid."""
    match = _XTRM_PERIOD.search(text or "")
    if match is None:
        return None
    try:
        start, end = (dt.date.fromisoformat(g) for g in match.groups())
    except ValueError:
        return None
    return (start, end) if start <= end else None


def date_es(value: dt.date) -> str:
    """'2 de octubre de 2026' (FAC-11: month in words, no format ambiguity)."""
    return f"{value.day} de {MONTHS_ES[value.month - 1]} de {value.year}"


def period_es(start: dt.date, end: dt.date) -> str:
    """'21 al 27 de septiembre de 2026'; each end carries its own month/year
    when the period crosses months or years."""
    if start == end:
        return date_es(start)
    if start.year != end.year:
        return f"{date_es(start)} al {date_es(end)}"
    if start.month != end.month:
        return (
            f"{start.day} de {MONTHS_ES[start.month - 1]} al {end.day} de "
            f"{MONTHS_ES[end.month - 1]} de {end.year}"
        )
    return f"{start.day} al {end.day} de {MONTHS_ES[end.month - 1]} de {end.year}"


def render_concept(
    template: str | None,
    payment_date: dt.date,
    work_start: dt.date | None,
    work_end: dt.date | None,
) -> tuple[str, list[str]]:
    """FAC-11: invoice description and the data still missing. Plain
    replacement (never str.format: the template is user text)."""
    missing: list[str] = []
    if work_start is not None and work_end is not None:
        periodo = period_es(work_start, work_end)
    else:
        periodo = MISSING_PERIOD
        missing.append("work_period")
    text = (template or DEFAULT_CONCEPT_TEMPLATE).replace("{periodo}", periodo)
    return text.replace("{fecha_pago}", date_es(payment_date)), missing


# --- Settings and clients (FAC-14) ----------------------------------------------------


async def get_settings(session: AsyncSession, space_id: uuid.UUID) -> BillingSettings | None:
    row: BillingSettings | None = await session.scalar(
        select(BillingSettings).where(BillingSettings.space_id == space_id)
    )
    return row


async def save_settings(
    session: AsyncSession, space_id: uuid.UUID, changes: dict[str, Any]
) -> BillingSettings:
    """FAC-14: SAT URLs, https only (also enforced by the schema). FAC-12:
    extra business days of the RFC's sixth digit."""
    row = await get_settings(session, space_id)
    if row is None:
        row = BillingSettings(space_id=space_id)
        session.add(row)
    for field in SAT_URL_FIELDS:
        if field in changes:
            value = (changes[field] or "").strip() or None
            if value is not None and not value.lower().startswith("https://"):
                raise _reject("La URL del portal del SAT debe empezar con https://")
            setattr(row, field, value)
    if changes.get("rfc_extra_days") is not None:
        row.rfc_extra_days = changes["rfc_extra_days"]  # FAC-12
    elif row.rfc_extra_days is None:
        row.rfc_extra_days = 0
    await session.commit()
    await session.refresh(row)
    return row


async def list_clients(
    session: AsyncSession, space_id: uuid.UUID, include_inactive: bool = False
) -> Sequence[BillingClient]:
    stmt = select(BillingClient).where(BillingClient.space_id == space_id)
    if not include_inactive:
        stmt = stmt.where(BillingClient.is_active.is_(True))
    return (await session.scalars(stmt.order_by(BillingClient.name))).all()


async def get_client(
    session: AsyncSession, space_id: uuid.UUID, client_id: uuid.UUID
) -> BillingClient:
    client: BillingClient | None = await session.scalar(
        select(BillingClient).where(
            BillingClient.id == client_id, BillingClient.space_id == space_id
        )
    )
    if client is None:
        raise _not_found("Cliente")
    return client


async def _active_client(
    session: AsyncSession, space_id: uuid.UUID, client_id: uuid.UUID
) -> BillingClient:
    client = await get_client(session, space_id, client_id)
    if not client.is_active:
        raise _reject("El cliente está desactivado")
    return client


async def create_client(
    session: AsyncSession, space_id: uuid.UUID, created_by: uuid.UUID, data: dict[str, Any]
) -> BillingClient:
    client = BillingClient(space_id=space_id, created_by=created_by, **data)
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client


async def update_client(
    session: AsyncSession, client: BillingClient, changes: dict[str, Any]
) -> BillingClient:
    for key, value in changes.items():
        setattr(client, key, value)
    await session.commit()
    await session.refresh(client)
    return client


async def delete_client(session: AsyncSession, client: BillingClient) -> None:
    """FAC-14/GLO-03: a client with payments or invoiceable accounts is only
    deactivated (accounts stop creating payments for it)."""
    used = await session.scalar(
        select(func.count(InvoiceablePayment.id)).where(InvoiceablePayment.client_id == client.id)
    )
    accounts = (
        await session.scalars(select(Account).where(Account.invoice_client_id == client.id))
    ).all()
    if used:
        client.is_active = False
        for account in accounts:
            account.invoice_client_id = None
    else:
        for account in accounts:
            account.invoice_client_id = None
        await session.flush()
        await session.delete(client)
    await session.commit()


# --- Computed state (FAC-04) ----------------------------------------------------------


@dataclass
class PaymentState:
    payment: InvoiceablePayment
    invoice: Invoice | None
    status: str
    account_id: uuid.UUID | None

    @property
    def period(self) -> dt.date:
        return fiscal_period(self.payment.payment_date)

    @property
    def mxn(self) -> Decimal | None:
        p = self.payment
        return fiscal_mxn(p.amount, p.currency, p.fiscal_fx_rate)

    @property
    def invoice_mismatch(self) -> bool:
        """FAC-04: the CFDI disagrees with the payment it covers."""
        inv = self.invoice
        return inv is not None and (
            inv.total != self.payment.amount or inv.currency != self.payment.currency
        )


def _filing_of_period(*extra: Any) -> Any:
    """EXISTS a filing whose fiscal month contains the payment (FAC-02/12)."""
    return (
        select(TaxFiling.id)
        .where(
            TaxFiling.space_id == InvoiceablePayment.space_id,
            TaxFiling.period_start <= InvoiceablePayment.payment_date,
            TaxFiling.period_end >= InvoiceablePayment.payment_date,
            *extra,
        )
        .exists()
    )


def _status_expr() -> Any:
    """FAC-04: excluded > pending_invoice > declared (an acuse of its period is
    unpaid) > paid (its period is declared and settled) > invoiced."""
    unpaid = _filing_of_period(TaxFiling.amount_due > 0, TaxFiling.paid_date.is_(None))
    return case(
        (InvoiceablePayment.is_excluded.is_(True), STATUS_EXCLUDED),
        (Invoice.id.is_(None), STATUS_PENDING),
        (unpaid, STATUS_DECLARED),
        (_filing_of_period(), STATUS_PAID),
        else_=STATUS_INVOICED,
    )


def _state_query(space_id: uuid.UUID) -> Select[Any]:
    return (
        select(InvoiceablePayment, Invoice, _status_expr(), Transaction.account_id)
        .outerjoin(Invoice, Invoice.payment_id == InvoiceablePayment.id)
        .outerjoin(Transaction, Transaction.id == InvoiceablePayment.transaction_id)
        .where(InvoiceablePayment.space_id == space_id)
    )


async def list_payments(
    session: AsyncSession,
    space_id: uuid.UUID,
    *,
    status_filter: str | None = None,
    client_id: uuid.UUID | None = None,
    period: dt.date | None = None,
) -> list[PaymentState]:
    stmt = _state_query(space_id)
    if status_filter is not None:
        stmt = stmt.where(_status_expr() == status_filter)
    if client_id is not None:
        stmt = stmt.where(InvoiceablePayment.client_id == client_id)
    if period is not None:
        start = fiscal_period(period)
        end = (start + dt.timedelta(days=32)).replace(day=1)
        stmt = stmt.where(
            InvoiceablePayment.payment_date >= start, InvoiceablePayment.payment_date < end
        )
    stmt = stmt.order_by(InvoiceablePayment.payment_date.desc(), InvoiceablePayment.created_at)
    rows = (await session.execute(stmt)).all()
    return [PaymentState(p, inv, st, acc) for p, inv, st, acc in rows]


async def get_payment(
    session: AsyncSession, space_id: uuid.UUID, payment_id: uuid.UUID
) -> InvoiceablePayment:
    payment: InvoiceablePayment | None = await session.scalar(
        select(InvoiceablePayment).where(
            InvoiceablePayment.id == payment_id, InvoiceablePayment.space_id == space_id
        )
    )
    if payment is None:
        raise _not_found("Cobro")
    return payment


async def payment_state(
    session: AsyncSession, space_id: uuid.UUID, payment_id: uuid.UUID
) -> PaymentState:
    row = (
        await session.execute(_state_query(space_id).where(InvoiceablePayment.id == payment_id))
    ).first()
    if row is None:
        raise _not_found("Cobro")
    return PaymentState(row[0], row[1], row[2], row[3])


async def summary(session: AsyncSession, space_id: uuid.UUID) -> dict[str, Any]:
    """FAC-04: count per status and pending amount per currency (SQL)."""
    status_expr = _status_expr()
    base = (
        select(
            status_expr,
            InvoiceablePayment.currency,
            func.count(),
            func.sum(InvoiceablePayment.amount),
        )
        .outerjoin(Invoice, Invoice.payment_id == InvoiceablePayment.id)
        .where(InvoiceablePayment.space_id == space_id)
        .group_by(status_expr, InvoiceablePayment.currency)
    )
    counts = dict.fromkeys(STATUSES, 0)
    pending: dict[str, Decimal] = {}
    for st, currency, count, total in (await session.execute(base)).all():
        counts[st] += int(count)
        if st == STATUS_PENDING:
            pending[currency] = Decimal(total)
    return {"counts": counts, "pending_amounts": pending}


async def files_by_id(
    session: AsyncSession, ids: Sequence[uuid.UUID | None]
) -> dict[uuid.UUID, StoredFile]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await session.scalars(select(StoredFile).where(StoredFile.id.in_(wanted)))).all()
    return {f.id: f for f in rows}


# --- Payments (FAC-01/02/05) ----------------------------------------------------------


def _validate_currency_rate(currency: str, rate: Decimal | None) -> Decimal | None:
    if currency not in SUPPORTED_CURRENCIES:
        raise _reject("Moneda no soportada")
    return None if currency == "MXN" else rate  # FAC-06: MXN uses rate 1


def _validate_work_period(start: dt.date | None, end: dt.date | None) -> None:
    if (start is None) != (end is None):
        raise _reject("Captura el inicio y el fin del periodo trabajado")
    if start is not None and end is not None and start > end:
        raise _reject("El periodo trabajado empieza después de terminar")


async def _attachable_file(
    session: AsyncSession, space_id: uuid.UUID, file_id: uuid.UUID | None
) -> uuid.UUID | None:
    if file_id is not None:
        await get_file(session, space_id, file_id)  # GLO-05
    return file_id


async def create_old_payment(
    session: AsyncSession, space: Space, created_by: uuid.UUID, data: dict[str, Any]
) -> InvoiceablePayment:
    """FAC-01b: a payment no longer in the wallet, captured without inventing a
    transaction. It may arrive already invoiced (its invoice in `invoice`)."""
    invoice_data = data.pop("invoice", None)
    await _active_client(session, space.id, data["client_id"])
    if data["payment_date"] > today_in_tz(space.timezone):
        raise _reject("La fecha del cobro no puede ser futura")
    data["fiscal_fx_rate"] = _validate_currency_rate(data["currency"], data.get("fiscal_fx_rate"))
    _validate_work_period(data.get("work_period_start"), data.get("work_period_end"))
    data["capture_file_id"] = await _attachable_file(session, space.id, data.get("capture_file_id"))
    payment = InvoiceablePayment(space_id=space.id, created_by=created_by, **data)
    session.add(payment)
    await session.flush()
    if invoice_data is not None:
        await _upsert_invoice(session, space, created_by, payment, invoice_data)
    await session.commit()
    await session.refresh(payment)
    return payment


LINKED_FIELDS = ("payment_date", "amount", "currency")


async def update_payment(
    session: AsyncSession, space: Space, payment: InvoiceablePayment, changes: dict[str, Any]
) -> InvoiceablePayment:
    """FAC-02: a payment born from an income follows its transaction; date,
    amount and currency are edited there. FAC-04: an invoiced payment can't be
    excluded."""
    if payment.transaction_id is not None:
        for field in LINKED_FIELDS:
            if field in changes and changes[field] != getattr(payment, field):
                raise _reject(
                    "Este cobro viene de un ingreso: edita fecha y monto en Transacciones"
                )
            changes.pop(field, None)
    if "payment_date" in changes and changes["payment_date"] > today_in_tz(space.timezone):
        raise _reject("La fecha del cobro no puede ser futura")
    if "client_id" in changes:
        await _active_client(session, space.id, changes["client_id"])
    if changes.get("is_excluded") and await _invoice_of(session, payment.id) is not None:
        raise _reject("Este cobro ya tiene factura; quítala antes de marcarlo no facturable")
    if "capture_file_id" in changes:
        await _attachable_file(session, space.id, changes["capture_file_id"])
    currency = changes.get("currency", payment.currency)
    rate = changes.get("fiscal_fx_rate", payment.fiscal_fx_rate)
    changes["fiscal_fx_rate"] = _validate_currency_rate(currency, rate)
    _validate_work_period(
        changes.get("work_period_start", payment.work_period_start),
        changes.get("work_period_end", payment.work_period_end),
    )
    for key, value in changes.items():
        setattr(payment, key, value)
    await session.commit()
    await session.refresh(payment)
    return payment


async def delete_payment(session: AsyncSession, payment: InvoiceablePayment) -> None:
    """FAC-05: only an old payment without invoice is deleted from here."""
    if payment.transaction_id is not None:
        raise _reject("Este cobro viene de un ingreso: márcalo como no facturable")
    if await _invoice_of(session, payment.id) is not None:
        raise _reject("Este cobro ya tiene factura; quítala antes de borrarlo")
    await session.delete(payment)
    await session.commit()


# --- Invoices (FAC-03) ----------------------------------------------------------------


async def _invoice_of(session: AsyncSession, payment_id: uuid.UUID) -> Invoice | None:
    invoice: Invoice | None = await session.scalar(
        select(Invoice).where(Invoice.payment_id == payment_id)
    )
    return invoice


async def _upsert_invoice(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    payment: InvoiceablePayment,
    data: dict[str, Any],
) -> Invoice:
    if payment.is_excluded:
        raise _reject("Este cobro está marcado como no facturable")
    if data["currency"] not in SUPPORTED_CURRENCIES:
        raise _reject("Moneda no soportada")
    cfdi_uuid = (data.get("cfdi_uuid") or "").strip().upper() or None
    data["cfdi_uuid"] = cfdi_uuid
    invoice = await _invoice_of(session, payment.id)
    if cfdi_uuid is not None:
        clash = await session.scalar(
            select(Invoice.id).where(
                Invoice.space_id == space.id,
                Invoice.cfdi_uuid == cfdi_uuid,
                Invoice.payment_id != payment.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Ese folio fiscal ya está registrado en otro cobro"
            )
    data["file_id"] = await _attachable_file(session, space.id, data.get("file_id"))
    if invoice is None:
        invoice = Invoice(space_id=space.id, payment_id=payment.id, created_by=created_by, **data)
        session.add(invoice)
    else:
        for key, value in data.items():
            setattr(invoice, key, value)
    await session.flush()
    return invoice


async def save_invoice(
    session: AsyncSession,
    space: Space,
    created_by: uuid.UUID,
    payment: InvoiceablePayment,
    data: dict[str, Any],
) -> None:
    await _upsert_invoice(session, space, created_by, payment, data)
    await session.commit()


async def delete_invoice(session: AsyncSession, payment: InvoiceablePayment) -> None:
    invoice = await _invoice_of(session, payment.id)
    if invoice is None:
        raise _not_found("Factura")
    await session.delete(invoice)
    await session.commit()


# --- Invoiceable accounts and the transaction hooks (FAC-01/05) -----------------------


async def _client_of_account(session: AsyncSession, account_id: uuid.UUID) -> uuid.UUID | None:
    client_id: uuid.UUID | None = await session.scalar(
        select(Account.invoice_client_id).where(Account.id == account_id)
    )
    return client_id


async def _payment_of_txn(session: AsyncSession, txn_id: uuid.UUID) -> InvoiceablePayment | None:
    payment: InvoiceablePayment | None = await session.scalar(
        select(InvoiceablePayment).where(InvoiceablePayment.transaction_id == txn_id)
    )
    return payment


def _payment_from_txn(txn: Transaction, client_id: uuid.UUID) -> InvoiceablePayment:
    work = parse_work_period(txn.description)
    return InvoiceablePayment(
        space_id=txn.space_id,
        client_id=client_id,
        transaction_id=txn.id,
        payment_date=txn.date,
        amount=txn.amount,
        currency=txn.currency,
        work_period_start=work[0] if work else None,
        work_period_end=work[1] if work else None,
        description=txn.description,
        created_by=txn.created_by,
    )


async def _keeps_payment(
    session: AsyncSession,
    old_account_id: uuid.UUID,
    new_type: TransactionType,
    new_account_id: uuid.UUID,
) -> bool:
    """An edited income keeps its payment unless it stops being an income or
    moves to an account that is not invoiceable."""
    if new_type != TransactionType.income:
        return False
    return new_account_id == old_account_id or (
        await _client_of_account(session, new_account_id) is not None
    )


async def guard_transaction_change(
    session: AsyncSession,
    txn: Transaction,
    *,
    new_type: TransactionType | None = None,
    new_account_id: uuid.UUID | None = None,
) -> None:
    """FAC-05: an invoiced payment pins its income (call before mutating;
    no new values = deletion)."""
    payment = await _payment_of_txn(session, txn.id)
    if payment is None or await _invoice_of(session, payment.id) is None:
        return
    if (
        new_type is not None
        and new_account_id is not None
        and await _keeps_payment(session, txn.account_id, new_type, new_account_id)
    ):
        return
    raise _reject(
        "Este ingreso ya está facturado; quita su factura en Facturación antes de "
        "borrarlo o cambiarlo de cuenta o de tipo"
    )


async def _sync_reminders(session: AsyncSession, space_id: uuid.UUID) -> None:
    """FAC-09: a payment that appears, moves or goes away moves its reminders."""
    from app.services.billing_reminders import sync_reminders

    space = await session.get(Space, space_id)
    if space is not None:
        await sync_reminders(session, space)


async def on_transaction_created(session: AsyncSession, txn: Transaction) -> None:
    """FAC-01a: an income into an invoiceable account becomes a payment."""
    if txn.type != TransactionType.income:
        return
    client_id = await _client_of_account(session, txn.account_id)
    if client_id is not None:
        session.add(_payment_from_txn(txn, client_id))
        await session.flush()
        await _sync_reminders(session, txn.space_id)


async def on_transaction_updated(
    session: AsyncSession, txn: Transaction, old_account_id: uuid.UUID
) -> None:
    """FAC-02: the payment follows its income; FAC-01a for an income that just
    became invoiceable. guard_transaction_change ran before the edit."""
    payment = await _payment_of_txn(session, txn.id)
    if payment is None:
        await on_transaction_created(session, txn)
        return
    if not await _keeps_payment(session, old_account_id, txn.type, txn.account_id):
        await session.delete(payment)
    else:
        if payment.payment_date != txn.date or payment.currency != txn.currency:
            payment.fiscal_fx_rate = None  # FAC-06: the rate belongs to the old date
        payment.payment_date = txn.date
        payment.amount = txn.amount
        payment.currency = txn.currency
    await session.flush()
    await _sync_reminders(session, txn.space_id)


async def on_transaction_deleted(session: AsyncSession, txn: Transaction) -> None:
    """FAC-05: a payment without invoice goes away with its income. FAC-13:
    deleting a tax expense from Transacciones only unlinks it from its filing
    (the payment record stays)."""
    payment = await _payment_of_txn(session, txn.id)
    if payment is not None:
        await session.delete(payment)
    filings = await session.scalars(
        select(TaxFiling).where(TaxFiling.expense_transaction_id == txn.id)
    )
    for filing in filings.all():
        filing.expense_transaction_id = None
    await session.flush()
    if payment is not None:
        await _sync_reminders(session, txn.space_id)


async def set_account_invoiceable(
    session: AsyncSession,
    space: Space,
    account_id: uuid.UUID,
    client_id: uuid.UUID | None,
    import_since: dt.date | None,
) -> tuple[Account, int]:
    """FAC-01: flag an account as invoiceable for a client and optionally
    import its existing incomes since a date (idempotent by transaction)."""
    from app.services.accounts import get_account

    account = await get_account(session, space.id, account_id)
    if client_id is not None:
        await _active_client(session, space.id, client_id)
    account.invoice_client_id = client_id
    imported = 0
    if client_id is not None and import_since is not None:
        txns = (
            await session.scalars(
                select(Transaction)
                .outerjoin(InvoiceablePayment, InvoiceablePayment.transaction_id == Transaction.id)
                .where(
                    Transaction.space_id == space.id,
                    Transaction.account_id == account.id,
                    Transaction.type == TransactionType.income,
                    Transaction.date >= import_since,
                    InvoiceablePayment.id.is_(None),
                )
                .order_by(Transaction.date)
            )
        ).all()
        for txn in txns:
            session.add(_payment_from_txn(txn, client_id))
        imported = len(txns)
    await session.commit()
    await session.refresh(account)
    return account, imported
