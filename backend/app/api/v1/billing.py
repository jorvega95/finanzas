"""Router: invoicing of freelance income and its RESICO declarations.
Implements FAC-01..FAC-14. Payments born from incomes are created
through /transactions (FAC-01a)."""

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response

from app.core.dates import today_in_tz
from app.core.deps import ActiveSpace, CurrentUser, DbSession, EditorSpace
from app.models.billing import StoredFile, TaxFiling
from app.schemas.billing import (
    BillingClientIn,
    BillingClientOut,
    BillingClientUpdate,
    BillingSettingsIn,
    BillingSettingsOut,
    BillingSummaryOut,
    CfdiCheckOut,
    FilingIn,
    FilingOut,
    FilingPaymentIn,
    FilingUpdate,
    InvoiceableAccountIn,
    InvoiceableAccountOut,
    InvoiceIn,
    InvoiceOut,
    InvoiceSheetOut,
    OldPaymentCreate,
    PaymentOut,
    PaymentUpdate,
    PeriodOut,
    PrefillItemOut,
    StoredFileOut,
)
from app.services import billing as svc
from app.services import billing_export, billing_reminders
from app.services import files as files_svc
from app.services import tax_filings as tax_svc
from app.services.billing import PaymentState

router = APIRouter(prefix="/billing", tags=["billing"])


def _file_out(
    files: dict[uuid.UUID, StoredFile], file_id: uuid.UUID | None
) -> StoredFileOut | None:
    stored = files.get(file_id) if file_id is not None else None
    return StoredFileOut.model_validate(stored) if stored is not None else None


def _out(state: PaymentState, files: dict[uuid.UUID, StoredFile]) -> PaymentOut:
    p, inv = state.payment, state.invoice
    return PaymentOut(
        id=p.id,
        client_id=p.client_id,
        transaction_id=p.transaction_id,
        account_id=state.account_id,
        payment_date=p.payment_date,
        period=state.period,
        amount=p.amount,
        currency=p.currency,
        fiscal_fx_rate=p.fiscal_fx_rate,
        mxn=state.mxn,
        work_period_start=p.work_period_start,
        work_period_end=p.work_period_end,
        description=p.description,
        notes=p.notes,
        is_excluded=p.is_excluded,
        status=state.status,
        invoice=None
        if inv is None
        else InvoiceOut(
            id=inv.id,
            cfdi_uuid=inv.cfdi_uuid,
            issue_date=inv.issue_date,
            total=inv.total,
            currency=inv.currency,
            fx_rate=inv.fx_rate,
            file=_file_out(files, inv.file_id),
            notes=inv.notes,
        ),
        invoice_mismatch=state.invoice_mismatch,
        capture_file=_file_out(files, p.capture_file_id),
    )


async def _outs(db: DbSession, states: list[PaymentState]) -> list[PaymentOut]:
    ids = [s.payment.capture_file_id for s in states] + [
        s.invoice.file_id for s in states if s.invoice is not None
    ]
    files = await svc.files_by_id(db, ids)
    return [_out(s, files) for s in states]


async def _payment_out(db: DbSession, space_id: uuid.UUID, payment_id: uuid.UUID) -> PaymentOut:
    return (await _outs(db, [await svc.payment_state(db, space_id, payment_id)]))[0]


# --- Settings and clients (FAC-14) ---------------------------------------------------


@router.get("/settings", response_model=BillingSettingsOut)
async def get_settings(db: DbSession, space_and_member: ActiveSpace) -> BillingSettingsOut:
    space, _ = space_and_member
    row = await svc.get_settings(db, space.id)
    return BillingSettingsOut.model_validate(row) if row else BillingSettingsOut()


@router.put("/settings", response_model=BillingSettingsOut)
async def save_settings(
    db: DbSession, space_and_member: EditorSpace, payload: BillingSettingsIn
) -> BillingSettingsOut:
    space, _ = space_and_member
    row = await svc.save_settings(db, space.id, payload.model_dump(exclude_unset=True))
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return BillingSettingsOut.model_validate(row)


@router.get("/clients", response_model=list[BillingClientOut])
async def list_clients(
    db: DbSession, space_and_member: ActiveSpace, include_inactive: bool = False
) -> list[BillingClientOut]:
    space, _ = space_and_member
    clients = await svc.list_clients(db, space.id, include_inactive)
    return [BillingClientOut.model_validate(c) for c in clients]


@router.post("/clients", response_model=BillingClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: BillingClientIn
) -> BillingClientOut:
    space, _ = space_and_member
    client = await svc.create_client(db, space.id, user.id, payload.model_dump())
    return BillingClientOut.model_validate(client)


@router.patch("/clients/{client_id}", response_model=BillingClientOut)
async def update_client(
    db: DbSession,
    space_and_member: EditorSpace,
    client_id: uuid.UUID,
    payload: BillingClientUpdate,
) -> BillingClientOut:
    space, _ = space_and_member
    client = await svc.get_client(db, space.id, client_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name", "") is None:
        changes.pop("name")
    client = await svc.update_client(db, client, changes)
    return BillingClientOut.model_validate(client)


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(db: DbSession, space_and_member: EditorSpace, client_id: uuid.UUID) -> None:
    """GLO-03: with payments it is deactivated instead."""
    space, _ = space_and_member
    await svc.delete_client(db, await svc.get_client(db, space.id, client_id))
    await billing_reminders.sync_and_commit(db, space)  # FAC-09


@router.put("/accounts/{account_id}", response_model=InvoiceableAccountOut)
async def set_invoiceable_account(
    db: DbSession,
    space_and_member: EditorSpace,
    account_id: uuid.UUID,
    payload: InvoiceableAccountIn,
) -> InvoiceableAccountOut:
    """FAC-01: incomes into the account become payments of the client; with
    `import_since`, its existing incomes since that date are imported."""
    space, _ = space_and_member
    account, imported = await svc.set_account_invoiceable(
        db, space, account_id, payload.client_id, payload.import_since
    )
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return InvoiceableAccountOut(
        account_id=account.id, client_id=account.invoice_client_id, imported=imported
    )


# --- Payments (FAC-01/02/04/05) ------------------------------------------------------


@router.get("/summary", response_model=BillingSummaryOut)
async def get_summary(db: DbSession, space_and_member: ActiveSpace) -> BillingSummaryOut:
    space, _ = space_and_member
    data = await svc.summary(db, space.id)
    return BillingSummaryOut(counts=data["counts"], pending_amounts=data["pending_amounts"])


@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(
    db: DbSession,
    space_and_member: ActiveSpace,
    status_filter: str | None = Query(default=None, alias="status", pattern="^[a-z_]+$"),
    client_id: uuid.UUID | None = None,
    period: dt.date | None = None,
) -> list[PaymentOut]:
    space, _ = space_and_member
    if status_filter is not None and status_filter not in svc.STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Estatus desconocido")
    states = await svc.list_payments(
        db, space.id, status_filter=status_filter, client_id=client_id, period=period
    )
    return await _outs(db, states)


@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
async def create_old_payment(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: OldPaymentCreate
) -> PaymentOut:
    """FAC-01b: a payment captured by hand (no longer in the wallet)."""
    space, _ = space_and_member
    data = payload.model_dump()
    payment = await svc.create_old_payment(db, space, user.id, data)
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _payment_out(db, space.id, payment.id)


@router.get("/payments/{payment_id}", response_model=PaymentOut)
async def get_payment(
    db: DbSession, space_and_member: ActiveSpace, payment_id: uuid.UUID
) -> PaymentOut:
    space, _ = space_and_member
    return await _payment_out(db, space.id, payment_id)


@router.patch("/payments/{payment_id}", response_model=PaymentOut)
async def update_payment(
    db: DbSession, space_and_member: EditorSpace, payment_id: uuid.UUID, payload: PaymentUpdate
) -> PaymentOut:
    space, _ = space_and_member
    payment = await svc.get_payment(db, space.id, payment_id)
    changes = payload.model_dump(exclude_unset=True)
    for required in ("client_id", "payment_date", "amount", "currency", "is_excluded"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    await svc.update_payment(db, space, payment, changes)
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _payment_out(db, space.id, payment_id)


@router.delete("/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment(
    db: DbSession, space_and_member: EditorSpace, payment_id: uuid.UUID
) -> None:
    """FAC-05: old payments without invoice only."""
    space, _ = space_and_member
    await svc.delete_payment(db, await svc.get_payment(db, space.id, payment_id))
    await billing_reminders.sync_and_commit(db, space)  # FAC-09


@router.get("/payments/{payment_id}/sheet", response_model=InvoiceSheetOut)
async def get_invoice_sheet(
    db: DbSession, space_and_member: ActiveSpace, payment_id: uuid.UUID
) -> InvoiceSheetOut:
    """FAC-11: data to capture in the SAT portal, description included."""
    space, _ = space_and_member
    out = await _payment_out(db, space.id, payment_id)
    client = await svc.get_client(db, space.id, out.client_id)
    description, missing = svc.render_concept(
        client.concept_template, out.payment_date, out.work_period_start, out.work_period_end
    )
    if out.currency != "MXN" and out.fiscal_fx_rate is None:
        missing.append("fiscal_fx_rate")
    settings_row = await svc.get_settings(db, space.id)
    return InvoiceSheetOut(
        payment=out,
        client=BillingClientOut.model_validate(client),
        description=description,
        missing=missing,
        sat_invoice_url=settings_row.sat_invoice_url if settings_row else None,
    )


@router.put("/payments/{payment_id}/invoice", response_model=PaymentOut)
async def save_invoice(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    payment_id: uuid.UUID,
    payload: InvoiceIn,
) -> PaymentOut:
    """FAC-03: create or replace the payment's invoice."""
    space, _ = space_and_member
    payment = await svc.get_payment(db, space.id, payment_id)
    await svc.save_invoice(db, space, user.id, payment, payload.model_dump())
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _payment_out(db, space.id, payment_id)


@router.delete("/payments/{payment_id}/invoice", response_model=PaymentOut)
async def delete_invoice(
    db: DbSession, space_and_member: EditorSpace, payment_id: uuid.UUID
) -> PaymentOut:
    space, _ = space_and_member
    await svc.delete_invoice(db, await svc.get_payment(db, space.id, payment_id))
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _payment_out(db, space.id, payment_id)


# --- Files (FAC-10) ------------------------------------------------------------------


@router.post("/files", response_model=StoredFileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    filename: str = Query(min_length=1, max_length=255),
) -> StoredFileOut:
    """FAC-10: the raw file is the request body (no multipart); the type is
    detected from its content. Attach it with its id afterwards."""
    space, _ = space_and_member
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > files_svc.MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "El archivo excede el máximo de 15 MB"
        )
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > files_svc.MAX_FILE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "El archivo excede el máximo de 15 MB"
            )
        chunks.append(chunk)
    stored = await files_svc.save_file(
        db, space.id, user.id, b"".join(chunks), filename, today_in_tz(space.timezone)
    )
    await db.commit()
    return StoredFileOut.model_validate(stored)


@router.get("/files/{file_id}")
async def download_file(
    db: DbSession, space_and_member: ActiveSpace, file_id: uuid.UUID, inline: bool = False
) -> FileResponse:
    """FAC-10: 404 for another space's file. Only PDFs and images may open in
    place; everything else is a download."""
    space, _ = space_and_member
    stored = await files_svc.get_file(db, space.id, file_id)
    disposition = "inline" if inline and stored.mime in files_svc.INLINE_MIMES else "attachment"
    return FileResponse(
        files_svc.file_path(stored),
        media_type=stored.mime,
        filename=stored.original_name,
        content_disposition_type=disposition,
        headers={"X-Content-Type-Options": "nosniff"},
    )


# --- Declarations (FAC-06/07/08/12/13) --------------------------------------------------


def _filing_out(filing: TaxFiling, files: dict[uuid.UUID, StoredFile]) -> FilingOut:
    return FilingOut(
        id=filing.id,
        period=filing.period_start,
        kind=filing.kind,
        filed_date=filing.filed_date,
        operation_number=filing.operation_number,
        capture_line=filing.capture_line,
        declared_income=filing.declared_income,
        isr_amount=filing.isr_amount,
        iva_amount=filing.iva_amount,
        amount_due=filing.amount_due,
        valid_until=filing.valid_until,
        ack_file=_file_out(files, filing.ack_file_id),
        paid_date=filing.paid_date,
        paid_amount=filing.paid_amount,
        receipt_file=_file_out(files, filing.receipt_file_id),
        expense_transaction_id=filing.expense_transaction_id,
        notes=filing.notes,
    )


async def _filing_files(db: DbSession, filings: list[TaxFiling]) -> dict[uuid.UUID, StoredFile]:
    return await svc.files_by_id(
        db, [f.ack_file_id for f in filings] + [f.receipt_file_id for f in filings]
    )


@router.get("/periods", response_model=list[PeriodOut])
async def list_periods(db: DbSession, space_and_member: ActiveSpace) -> list[PeriodOut]:
    """FAC-06/07/08/12: one row per fiscal month, newest first."""
    space, _ = space_and_member
    periods = await tax_svc.list_periods(db, space)
    files = await _filing_files(db, [f for p in periods for f in p.filings])
    return [
        PeriodOut(
            period=p.period,
            status=p.status,
            is_overdue=p.is_overdue,
            deadline=p.deadline,
            payment_deadline=p.payment_deadline,
            to_declare=p.to_declare,
            missing_rates=p.missing_rates,
            pending_invoice=p.pending_invoice,
            isr_rate=p.isr_rate,
            isr_estimate=p.isr_estimate,
            sat_prefill=p.sat_prefill,
            prefill_unknown=p.prefill_unknown,
            exclude_from_prefill=[PrefillItemOut.model_validate(i) for i in p.exclude_from_prefill],
            add_to_prefill=[PrefillItemOut.model_validate(i) for i in p.add_to_prefill],
            amount_due=p.amount_due,
            payment_ids=[s.payment.id for s in p.payments],
            filings=[_filing_out(f, files) for f in p.filings],
        )
        for p in periods
    ]


async def _one_filing_out(db: DbSession, filing: TaxFiling) -> FilingOut:
    return _filing_out(filing, await _filing_files(db, [filing]))


@router.post("/filings", response_model=FilingOut, status_code=status.HTTP_201_CREATED)
async def create_filing(
    db: DbSession, space_and_member: EditorSpace, user: CurrentUser, payload: FilingIn
) -> FilingOut:
    """FAC-12: the acuse of a past month; `payment` registers it as paid."""
    space, _ = space_and_member
    data = payload.model_dump()
    if data["payment"] is None:
        data.pop("payment")
    filing = await tax_svc.create_filing(db, space, user.id, data)
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _one_filing_out(db, filing)


@router.patch("/filings/{filing_id}", response_model=FilingOut)
async def update_filing(
    db: DbSession, space_and_member: EditorSpace, filing_id: uuid.UUID, payload: FilingUpdate
) -> FilingOut:
    space, _ = space_and_member
    filing = await tax_svc.get_filing(db, space.id, filing_id)
    changes = payload.model_dump(exclude_unset=True)
    for required in ("kind", "filed_date", "isr_amount", "iva_amount", "amount_due"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    filing = await tax_svc.update_filing(db, space, filing, changes)
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _one_filing_out(db, filing)


@router.delete("/filings/{filing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_filing(db: DbSession, space_and_member: EditorSpace, filing_id: uuid.UUID) -> None:
    space, _ = space_and_member
    await tax_svc.delete_filing(db, await tax_svc.get_filing(db, space.id, filing_id))
    await billing_reminders.sync_and_commit(db, space)  # FAC-09


@router.put("/filings/{filing_id}/payment", response_model=FilingOut)
async def set_filing_payment(
    db: DbSession,
    space_and_member: EditorSpace,
    user: CurrentUser,
    filing_id: uuid.UUID,
    payload: FilingPaymentIn,
) -> FilingOut:
    """FAC-12/13: register or replace the payment (and its expense)."""
    space, _ = space_and_member
    filing = await tax_svc.get_filing(db, space.id, filing_id)
    filing = await tax_svc.set_payment(db, space, user.id, filing, payload.model_dump())
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _one_filing_out(db, filing)


@router.delete("/filings/{filing_id}/payment", response_model=FilingOut)
async def remove_filing_payment(
    db: DbSession, space_and_member: EditorSpace, filing_id: uuid.UUID
) -> FilingOut:
    space, _ = space_and_member
    filing = await tax_svc.get_filing(db, space.id, filing_id)
    filing = await tax_svc.remove_payment(db, space, filing)
    await billing_reminders.sync_and_commit(db, space)  # FAC-09
    return await _one_filing_out(db, filing)


# --- CFDI reading and yearly export (FAC-15/16) -------------------------------------------


@router.get("/payments/{payment_id}/cfdi", response_model=CfdiCheckOut)
async def check_cfdi(
    db: DbSession, space_and_member: ActiveSpace, payment_id: uuid.UUID, file_id: uuid.UUID
) -> CfdiCheckOut:
    """FAC-15: read the CFDI of an uploaded file (zip or xml) to prefill the
    invoice and flag what disagrees with the payment."""
    space, _ = space_and_member
    state = await svc.payment_state(db, space.id, payment_id)
    stored = await files_svc.get_file(db, space.id, file_id)
    data = (
        billing_export.read_file_cfdi(stored)
        if stored.mime in ("application/zip", "application/xml")
        else None
    )
    if data is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "No se encontró un CFDI (XML) en el archivo"
        )
    client = await svc.get_client(db, space.id, state.payment.client_id)
    return CfdiCheckOut(
        uuid=data.uuid,
        issue_date=data.issue_date,
        total=data.total,
        currency=data.currency,
        fx_rate=data.fx_rate,
        issuer_rfc=data.issuer_rfc,
        receiver_rfc=data.receiver_rfc,
        receiver_name=data.receiver_name,
        iva_rates=data.iva_rates,
        warnings=billing_export.cfdi_warnings(data, state, client),
    )


@router.get("/export")
async def export_year(
    db: DbSession, space_and_member: ActiveSpace, year: int = Query(ge=2000, le=2100)
) -> Response:
    """FAC-16: a .zip with a folder per month and CSV summaries."""
    space, _ = space_and_member
    content = await billing_export.export_year(db, space, year)
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="facturacion-{year}.zip"',
            "X-Content-Type-Options": "nosniff",
        },
    )
