"""CFDI checks and the yearly export. Implements FAC-15 and FAC-16.

FAC-15: the CFDI of an uploaded file is compared with its payment.
FAC-16: one .zip per year with a folder per fiscal month (the guide's
layout) plus CSV summaries of payments and declarations.
"""

import csv
import datetime as dt
import io
import uuid
import zipfile
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import BillingClient, StoredFile, TaxFiling
from app.models.spaces import Space
from app.services import billing, tax_filings
from app.services.billing import PaymentState
from app.services.cfdi import CfdiData, read_cfdi
from app.services.files import file_path

ZERO_RATE = 0


def cfdi_warnings(data: CfdiData, state: PaymentState, client: BillingClient | None) -> list[str]:
    """FAC-15: codes of what disagrees between the CFDI and the payment."""
    p = state.payment
    warnings: list[str] = []
    if data.total is not None and data.total != p.amount:
        warnings.append("total")
    if data.currency is not None and data.currency != p.currency:
        warnings.append("currency")
    if (
        data.fx_rate is not None
        and p.fiscal_fx_rate is not None
        and data.fx_rate.quantize(p.fiscal_fx_rate) != p.fiscal_fx_rate
    ):
        warnings.append("fx_rate")
    if data.issue_date is not None and (
        data.issue_date.year,
        data.issue_date.month,
    ) != (p.payment_date.year, p.payment_date.month):
        warnings.append("issue_month")  # FAC-08: the SAT will prefill it elsewhere
    if any(rate != ZERO_RATE for rate in data.iva_rates):
        warnings.append("iva")  # exports carry IVA at 0%
    if (
        client is not None
        and client.tax_id
        and data.receiver_rfc
        and data.receiver_rfc.upper() != client.tax_id.upper()
    ):
        warnings.append("receiver")
    return warnings


def read_file_cfdi(stored: StoredFile) -> CfdiData | None:
    return read_cfdi(file_path(stored).read_bytes())


# --- Yearly export (FAC-16) -----------------------------------------------------------


@dataclass
class _Entry:
    stored: StoredFile
    name: str


def _ext(stored: StoredFile) -> str:
    return stored.storage_path.rsplit(".", 1)[-1]


def _unique(name: str, used: set[str]) -> str:
    stem, dot, ext = name.rpartition(".")
    candidate, n = name, 2
    while candidate in used:
        candidate = f"{stem}-{n}{dot}{ext}"
        n += 1
    used.add(candidate)
    return candidate


async def export_year(session: AsyncSession, space: Space, year: int) -> bytes:
    states = [
        s
        for s in await billing.list_payments(session, space.id)
        if s.payment.payment_date.year == year
    ]
    filings = [
        f for f in await tax_filings.list_filings(session, space.id) if f.period_start.year == year
    ]
    file_ids: list[uuid.UUID | None] = [s.payment.capture_file_id for s in states]
    file_ids += [s.invoice.file_id for s in states if s.invoice is not None]
    file_ids += [f.ack_file_id for f in filings] + [f.receipt_file_id for f in filings]
    files = await billing.files_by_id(session, file_ids)
    clients = {c.id: c.name for c in await billing.list_clients(session, space.id, True)}

    entries: list[_Entry] = []
    used: set[str] = set()

    def add(file_id: uuid.UUID | None, folder: dt.date, base: str) -> str:
        stored = files.get(file_id) if file_id is not None else None
        if stored is None:
            return ""
        name = _unique(f"{folder:%Y-%m}/{base}.{_ext(stored)}", used)
        entries.append(_Entry(stored, name))
        return name

    payments_csv = io.StringIO()
    writer = csv.writer(payments_csv)
    writer.writerow(
        [
            "fecha_cobro",
            "periodo",
            "cliente",
            "monto",
            "moneda",
            "tipo_cambio",
            "mxn",
            "estatus",
            "folio_fiscal",
            "fecha_emision",
            "factura",
            "captura",
        ]
    )
    for s in sorted(states, key=lambda s: s.payment.payment_date):
        p, inv = s.payment, s.invoice
        day = f"{p.payment_date:%Y-%m-%d}"
        invoice_name = add(inv.file_id if inv else None, s.period, f"factura-{day}")
        capture_name = add(p.capture_file_id, s.period, f"captura-wallet-{day}")
        writer.writerow(
            [
                p.payment_date.isoformat(),
                f"{s.period:%Y-%m}",
                clients.get(p.client_id, ""),
                p.amount,
                p.currency,
                p.fiscal_fx_rate or "",
                s.mxn if s.mxn is not None else "",
                s.status,
                inv.cfdi_uuid or "" if inv else "",
                inv.issue_date.isoformat() if inv else "",
                invoice_name,
                capture_name,
            ]
        )

    filings_csv = io.StringIO()
    writer = csv.writer(filings_csv)
    writer.writerow(
        [
            "periodo",
            "tipo",
            "presentada",
            "numero_operacion",
            "linea_captura",
            "ingresos_declarados",
            "isr",
            "iva",
            "a_pagar",
            "pagada",
            "importe_pagado",
            "acuse",
            "recibo",
        ]
    )
    for f in filings:
        month = f"{f.period_start:%Y-%m}"
        writer.writerow(
            [
                month,
                f.kind.value,
                f.filed_date.isoformat(),
                f.operation_number or "",
                f.capture_line or "",
                f.declared_income if f.declared_income is not None else "",
                f.isr_amount,
                f.iva_amount,
                f.amount_due,
                f.paid_date.isoformat() if f.paid_date else "",
                f.paid_amount if f.paid_amount is not None else "",
                add(f.ack_file_id, f.period_start, f"acuse-{_kind_name(f)}-{month}"),
                add(f.receipt_file_id, f.period_start, f"recibo-pago-{month}"),
            ]
        )

    buffer = io.BytesIO()
    missing: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("cobros.csv", "﻿" + payments_csv.getvalue())  # BOM: Excel UTF-8
        archive.writestr("declaraciones.csv", "﻿" + filings_csv.getvalue())
        for entry in entries:
            try:
                archive.write(file_path(entry.stored), entry.name)
            except Exception:
                missing.append(f"{entry.name} ({entry.stored.original_name})")
        if missing:
            archive.writestr("faltantes.txt", "\n".join(missing) + "\n")
    return buffer.getvalue()


def _kind_name(filing: TaxFiling) -> str:
    return "normal" if filing.kind.value == "normal" else "complementaria"
