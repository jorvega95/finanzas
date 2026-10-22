"""Invoicing of freelance income: FAC-01..FAC-06 (per payment), FAC-10,
FAC-11 and FAC-14.

Mandatory case 21.
"""

import datetime as dt
from decimal import Decimal

import pytest
from freezegun import freeze_time

from app.core.config import settings
from app.services.billing import (
    fiscal_mxn,
    parse_work_period,
    period_es,
    render_concept,
)
from tests.conftest import bootstrap_space
from tests.test_accounts import add_member
from tests.test_wallets import post_txn

PDF = b"%PDF-1.7\n%fake invoice\n"
ZIP = b"PK\x03\x04" + b"\x00" * 26
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
CFDI_UUID = "6f1e2c3a-1b2c-4d5e-8f90-a1b2c3d4e5f6"


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    """FAC-10: every test writes its files to a throwaway directory."""
    monkeypatch.setattr(settings, "files_dir", str(tmp_path / "files"))
    return tmp_path / "files"


async def make_client(client, ctx, **body):
    payload = {
        "name": "Greenlight",
        "tax_id": "XEXX010101000",
        "fiscal_regime": "616",
        "cfdi_use": "S01",
        "product_code": "81112000",
        "unit_code": "E48",
        **body,
    }
    res = await client.post("/api/v1/billing/clients", headers=ctx["headers"], json=payload)
    assert res.status_code == 201, res.text
    return res.json()


async def make_invoiceable(client, ctx, account_id, client_id, expected=200, **extra):
    res = await client.put(
        f"/api/v1/billing/accounts/{account_id}",
        headers=ctx["headers"],
        json={"client_id": client_id, **extra},
    )
    assert res.status_code == expected, res.text
    return res.json()


def usd_income(ctx, amount="325.00", day="2026-10-02", description="Payment"):
    return {
        "type": "income",
        "date": day,
        "amount": amount,
        "currency": "USD",
        "fx_rate_override": "18.05",  # FX-03 rate; independent of the fiscal one
        "category_id": ctx["income_categories"]["Freelance"]["id"],
        "account_id": ctx["accounts"]["Dólares"]["id"],
        "description": description,
    }


async def payments(client, ctx, **params):
    res = await client.get("/api/v1/billing/payments", headers=ctx["headers"], params=params)
    assert res.status_code == 200, res.text
    return res.json()


async def upload(client, ctx, content, filename="factura.zip", expected=201):
    res = await client.post(
        "/api/v1/billing/files",
        headers={**ctx["headers"], "Content-Type": "application/octet-stream"},
        params={"filename": filename},
        content=content,
    )
    assert res.status_code == expected, res.text
    return res.json()


async def save_invoice(client, ctx, payment_id, expected=200, **body):
    payload = {"issue_date": "2026-10-02", "total": "325.00", "currency": "USD", **body}
    res = await client.put(
        f"/api/v1/billing/payments/{payment_id}/invoice", headers=ctx["headers"], json=payload
    )
    assert res.status_code == expected, res.text
    return res.json()


async def setup(client):
    ctx = await bootstrap_space(client)
    greenlight = await make_client(client, ctx)
    await make_invoiceable(client, ctx, ctx["accounts"]["Dólares"]["id"], greenlight["id"])
    return ctx, greenlight


# --- Mandatory case 21: FAC-01/02/04/05 -------------------------------------------------


@freeze_time("2026-10-21 12:00:00")
async def test_fac_mandatory_case_21(client):
    ctx, greenlight = await setup(client)
    wallet = ctx["accounts"]["Dólares"]["id"]

    # FAC-01a: an income into the invoiceable account becomes a pending payment.
    txn = await post_txn(client, ctx, **usd_income(ctx))
    [payment] = await payments(client, ctx)
    assert payment["transaction_id"] == txn["id"]
    assert payment["status"] == "pending_invoice"
    assert payment["period"] == "2026-10-01"  # FAC-02
    assert payment["amount"] == "325.00" and payment["currency"] == "USD"
    assert payment["account_id"] == wallet

    # TXN-02: a withdrawal (transfer) never creates a payment.
    await post_txn(
        client,
        ctx,
        type="transfer",
        date="2026-10-03",
        amount="300.00",
        currency="USD",
        account_id=wallet,
        account_to_id=ctx["accounts"]["Débito"]["id"],
        amount_to="5400.00",
        fx_rate_override="18.00",
    )
    assert len(await payments(client, ctx)) == 1

    # FAC-04: with its invoice it is invoiced; FAC-05: the income is pinned.
    body = await save_invoice(client, ctx, payment["id"], cfdi_uuid=CFDI_UUID)
    assert body["status"] == "invoiced"
    assert body["invoice"]["cfdi_uuid"] == CFDI_UUID.upper()
    res = await client.delete(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"])
    assert res.status_code == 422
    assert "facturado" in res.json()["detail"]

    # Removing the invoice frees it: deleting the income deletes the payment.
    res = await client.delete(
        f"/api/v1/billing/payments/{payment['id']}/invoice", headers=ctx["headers"]
    )
    assert res.status_code == 200 and res.json()["status"] == "pending_invoice"
    res = await client.delete(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"])
    assert res.status_code == 204
    assert await payments(client, ctx) == []

    # FAC-01b/06: an old payment, Sep 25 at 17.5030 ⇒ period Sep, 1,896.10 MXN.
    res = await client.post(
        "/api/v1/billing/payments",
        headers=ctx["headers"],
        json={
            "client_id": greenlight["id"],
            "payment_date": "2026-09-25",
            "amount": "108.33",
            "currency": "USD",
            "fiscal_fx_rate": "17.5030",
        },
    )
    assert res.status_code == 201, res.text
    old = res.json()
    assert old["transaction_id"] is None
    assert old["period"] == "2026-09-01"
    assert old["mxn"] == "1896.10"
    assert old["status"] == "pending_invoice"


# --- FAC-01: import existing incomes, idempotent ------------------------------------------


@freeze_time("2026-10-21 12:00:00")
async def test_fac01_import_existing_incomes_is_idempotent(client):
    ctx = await bootstrap_space(client)
    greenlight = await make_client(client, ctx)
    wallet = ctx["accounts"]["Dólares"]["id"]
    # Incomes recorded before the account was invoiceable: no payments yet.
    await post_txn(client, ctx, **usd_income(ctx, "100.00", "2026-08-30"))
    await post_txn(client, ctx, **usd_income(ctx, "108.33", "2026-09-25"))
    await post_txn(client, ctx, **usd_income(ctx, "325.00", "2026-10-02"))
    assert await payments(client, ctx) == []

    body = await make_invoiceable(client, ctx, wallet, greenlight["id"], import_since="2026-09-01")
    assert body["imported"] == 2
    body = await make_invoiceable(client, ctx, wallet, greenlight["id"], import_since="2026-09-01")
    assert body["imported"] == 0
    assert sorted(p["payment_date"] for p in await payments(client, ctx)) == [
        "2026-09-25",
        "2026-10-02",
    ]
    account = (await client.get(f"/api/v1/accounts/{wallet}", headers=ctx["headers"])).json()
    assert account["invoice_client_id"] == greenlight["id"]


async def test_fac01_other_accounts_and_expenses_are_not_invoiceable(client):
    ctx, _ = await setup(client)
    # Income into a non-invoiceable account, and an expense from the wallet.
    await post_txn(
        client,
        ctx,
        type="income",
        date="2026-06-01",
        amount="5000.00",
        currency="MXN",
        category_id=ctx["income_categories"]["Nómina"]["id"],
        account_id=ctx["accounts"]["Débito"]["id"],
    )
    await post_txn(
        client,
        ctx,
        type="expense",
        date="2026-06-02",
        amount="3.00",
        currency="USD",
        fx_rate_override="18.00",
        category_id=ctx["expense_categories"]["Otros"]["id"],
        account_id=ctx["accounts"]["Dólares"]["id"],
    )
    assert await payments(client, ctx) == []


# --- FAC-02/05: the payment follows its income --------------------------------------------


async def test_fac02_payment_follows_income_edits(client):
    ctx, _ = await setup(client)
    txn = await post_txn(client, ctx, **usd_income(ctx, day="2026-06-02"))
    [payment] = await payments(client, ctx)
    res = await client.patch(
        f"/api/v1/billing/payments/{payment['id']}",
        headers=ctx["headers"],
        json={"fiscal_fx_rate": "18.0692"},
    )
    assert res.json()["mxn"] == "5872.49"

    edited = {**usd_income(ctx, "330.00", "2026-06-03")}
    res = await client.put(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"], json=edited)
    assert res.status_code == 200, res.text
    [payment] = await payments(client, ctx)
    assert payment["amount"] == "330.00"
    assert payment["payment_date"] == "2026-06-03"
    assert payment["fiscal_fx_rate"] is None  # FAC-06: the rate belonged to the old date

    # Date/amount of an income's payment are edited in Transacciones.
    res = await client.patch(
        f"/api/v1/billing/payments/{payment['id']}",
        headers=ctx["headers"],
        json={"amount": "1.00"},
    )
    assert res.status_code == 422
    # And it is excluded, not deleted, from here.
    res = await client.delete(f"/api/v1/billing/payments/{payment['id']}", headers=ctx["headers"])
    assert res.status_code == 422
    res = await client.patch(
        f"/api/v1/billing/payments/{payment['id']}",
        headers=ctx["headers"],
        json={"is_excluded": True},
    )
    assert res.json()["status"] == "excluded"
    assert len(await payments(client, ctx, status="pending_invoice")) == 0
    assert len(await payments(client, ctx, status="excluded")) == 1


async def test_fac05_invoiced_income_cannot_change_type_or_leave_account(client):
    ctx, _ = await setup(client)
    txn = await post_txn(client, ctx, **usd_income(ctx, day="2026-06-02"))
    [payment] = await payments(client, ctx)
    await save_invoice(client, ctx, payment["id"], issue_date="2026-06-02")

    as_expense = {
        **usd_income(ctx, day="2026-06-02"),
        "type": "expense",
        "category_id": ctx["expense_categories"]["Otros"]["id"],
    }
    res = await client.put(
        f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"], json=as_expense
    )
    assert res.status_code == 422
    # Editing the amount keeps the payment and flags the mismatch (FAC-04).
    res = await client.put(
        f"/api/v1/transactions/{txn['id']}",
        headers=ctx["headers"],
        json=usd_income(ctx, "300.00", "2026-06-02"),
    )
    assert res.status_code == 200, res.text
    [payment] = await payments(client, ctx)
    assert payment["status"] == "invoiced"
    assert payment["invoice_mismatch"] is True


async def test_fac05_pending_income_moved_away_drops_its_payment(client):
    ctx, _ = await setup(client)
    txn = await post_txn(client, ctx, **usd_income(ctx, day="2026-06-02"))
    assert len(await payments(client, ctx)) == 1
    as_expense = {
        **usd_income(ctx, day="2026-06-02"),
        "type": "expense",
        "category_id": ctx["expense_categories"]["Otros"]["id"],
    }
    res = await client.put(
        f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"], json=as_expense
    )
    assert res.status_code == 200, res.text
    assert await payments(client, ctx) == []


# --- FAC-03: one invoice per payment, folio unique ----------------------------------------


@freeze_time("2026-10-21 12:00:00")
async def test_fac03_cfdi_uuid_unique_and_excluded_payment_rejected(client):
    ctx, greenlight = await setup(client)
    await post_txn(client, ctx, **usd_income(ctx, "20.00", "2026-10-01"))
    await post_txn(client, ctx, **usd_income(ctx, "200.00", "2026-10-02"))
    first, second = sorted(await payments(client, ctx), key=lambda p: p["payment_date"])
    await save_invoice(client, ctx, first["id"], total="20.00", cfdi_uuid=CFDI_UUID)
    await save_invoice(client, ctx, second["id"], total="200.00", cfdi_uuid=CFDI_UUID, expected=409)
    # Replacing the invoice of the same payment is fine (1:1, FAC-03).
    body = await save_invoice(client, ctx, first["id"], total="20.00", cfdi_uuid=CFDI_UUID)
    assert body["invoice"]["total"] == "20.00"

    res = await client.patch(
        f"/api/v1/billing/payments/{first['id']}",
        headers=ctx["headers"],
        json={"is_excluded": True},
    )
    assert res.status_code == 422  # invoiced ⇒ can't be excluded
    res = await client.patch(
        f"/api/v1/billing/payments/{second['id']}",
        headers=ctx["headers"],
        json={"is_excluded": True},
    )
    assert res.status_code == 200
    await save_invoice(client, ctx, second["id"], total="200.00", expected=422)

    summary = (await client.get("/api/v1/billing/summary", headers=ctx["headers"])).json()
    assert summary["counts"] == {
        "pending_invoice": 0,
        "invoiced": 1,
        "declared": 0,
        "paid": 0,
        "excluded": 1,
    }


@freeze_time("2026-10-21 12:00:00")
async def test_fac01b_old_payment_arrives_invoiced_and_rules(client):
    ctx, greenlight = await setup(client)
    base = {
        "client_id": greenlight["id"],
        "payment_date": "2026-09-25",
        "amount": "108.33",
        "currency": "USD",
    }
    res = await client.post(
        "/api/v1/billing/payments",
        headers=ctx["headers"],
        json={**base, "invoice": {"issue_date": "2026-10-07", "total": "108.33"}},
    )
    assert res.status_code == 201, res.text
    old = res.json()
    assert old["status"] == "invoiced"
    assert old["invoice"]["issue_date"] == "2026-10-07"
    assert old["period"] == "2026-09-01"  # FAC-02: payment month, not invoice month
    # Invoiced ⇒ not deletable; without invoice ⇒ deletable.
    url = f"/api/v1/billing/payments/{old['id']}"
    assert (await client.delete(url, headers=ctx["headers"])).status_code == 422
    await client.delete(f"{url}/invoice", headers=ctx["headers"])
    assert (await client.delete(url, headers=ctx["headers"])).status_code == 204

    future = {**base, "payment_date": "2026-10-22"}
    res = await client.post("/api/v1/billing/payments", headers=ctx["headers"], json=future)
    assert res.status_code == 422
    half_period = {**base, "work_period_start": "2026-09-21"}
    res = await client.post("/api/v1/billing/payments", headers=ctx["headers"], json=half_period)
    assert res.status_code == 422
    # FAC-06: an MXN payment needs no fiscal rate (its pesos are the amount).
    mxn = {**base, "currency": "MXN", "amount": "5000.00", "fiscal_fx_rate": "17.0000"}
    res = await client.post("/api/v1/billing/payments", headers=ctx["headers"], json=mxn)
    assert res.json()["fiscal_fx_rate"] is None and res.json()["mxn"] == "5000.00"


# --- FAC-06/11: pure helpers and the invoice sheet -----------------------------------------


def test_fac06_fiscal_mxn_rounding():
    assert fiscal_mxn(Decimal("108.33"), "USD", Decimal("17.5030")) == Decimal("1896.10")
    assert fiscal_mxn(Decimal("325.00"), "USD", Decimal("18.0692")) == Decimal("5872.49")
    assert fiscal_mxn(Decimal("10.00"), "USD", None) is None
    assert fiscal_mxn(Decimal("10.00"), "MXN", None) == Decimal("10.00")


def test_fac11_spanish_periods():
    d = dt.date
    assert period_es(d(2026, 9, 21), d(2026, 9, 27)) == "21 al 27 de septiembre de 2026"
    assert period_es(d(2026, 9, 28), d(2026, 10, 4)) == "28 de septiembre al 4 de octubre de 2026"
    assert (
        period_es(d(2026, 12, 28), d(2027, 1, 3)) == "28 de diciembre de 2026 al 3 de enero de 2027"
    )
    assert period_es(d(2026, 9, 21), d(2026, 9, 21)) == "21 de septiembre de 2026"


def test_fac11_parse_xtrm_period_and_template():
    assert parse_work_period("Payment for 2026-09-21 to 2026-09-27") == (
        dt.date(2026, 9, 21),
        dt.date(2026, 9, 27),
    )
    assert parse_work_period("Payment for 2026-09-27 to 2026-09-21") is None
    assert parse_work_period("Pago") is None
    text, missing = render_concept(
        "Pago {fecha_pago} {periodo} {otro}", dt.date(2026, 10, 2), None, None
    )
    assert text == "Pago 2 de octubre de 2026 [periodo trabajado] {otro}"
    assert missing == ["work_period"]


async def test_fac11_sheet_builds_description_from_xtrm_payment(client):
    ctx, greenlight = await setup(client)
    await client.put(
        "/api/v1/billing/settings",
        headers=ctx["headers"],
        json={"sat_invoice_url": "https://portal.example/factura"},
    )
    await post_txn(
        client,
        ctx,
        **usd_income(ctx, day="2026-06-02", description="Payment for 2026-05-21 to 2026-05-27"),
    )
    [payment] = await payments(client, ctx)
    assert payment["work_period_start"] == "2026-05-21"

    res = await client.get(
        f"/api/v1/billing/payments/{payment['id']}/sheet", headers=ctx["headers"]
    )
    sheet = res.json()
    assert sheet["description"] == (
        "Servicios de entrenamiento y evaluación de modelos de IA periodo 21 al 27 de mayo "
        "de 2026 pago recibido el 2 de junio de 2026"
    )
    assert sheet["missing"] == ["fiscal_fx_rate"]
    assert sheet["client"]["tax_id"] == "XEXX010101000"
    assert sheet["sat_invoice_url"] == "https://portal.example/factura"


# --- FAC-14: settings and clients -----------------------------------------------------------


async def test_fac14_sat_urls_https_only(client):
    ctx = await bootstrap_space(client)
    url = "/api/v1/billing/settings"
    assert (await client.get(url, headers=ctx["headers"])).json()["sat_invoice_url"] is None
    res = await client.put(url, headers=ctx["headers"], json={"sat_filing_url": "http://x.mx"})
    assert res.status_code == 422
    res = await client.put(
        url, headers=ctx["headers"], json={"sat_filing_url": "javascript:alert(1)"}
    )
    assert res.status_code == 422
    res = await client.put(url, headers=ctx["headers"], json={"sat_filing_url": "https://x.mx/d"})
    assert res.json()["sat_filing_url"] == "https://x.mx/d"
    res = await client.put(url, headers=ctx["headers"], json={"sat_filing_url": ""})
    assert res.json()["sat_filing_url"] is None


async def test_fac14_client_with_payments_is_deactivated(client):
    ctx, greenlight = await setup(client)
    await post_txn(client, ctx, **usd_income(ctx, day="2026-06-02"))
    url = f"/api/v1/billing/clients/{greenlight['id']}"
    assert (await client.delete(url, headers=ctx["headers"])).status_code == 204
    listed = await client.get(
        "/api/v1/billing/clients?include_inactive=true", headers=ctx["headers"]
    )
    assert [c["is_active"] for c in listed.json()] == [False]
    # Its account is no longer invoiceable: new incomes create nothing.
    await post_txn(client, ctx, **usd_income(ctx, day="2026-06-03"))
    assert len(await payments(client, ctx)) == 1

    unused = await make_client(client, ctx, name="Otro")
    url = f"/api/v1/billing/clients/{unused['id']}"
    assert (await client.delete(url, headers=ctx["headers"])).status_code == 204
    assert (await client.patch(url, headers=ctx["headers"], json={})).status_code == 404


# --- FAC-10: files ----------------------------------------------------------------------------


async def test_fac10_upload_attach_download(client, files_dir):
    ctx, _ = await setup(client)
    await post_txn(client, ctx, **usd_income(ctx, day="2026-06-02"))
    [payment] = await payments(client, ctx)

    stored = await upload(client, ctx, ZIP, "../../etc/factura 2026.zip")
    assert stored["mime"] == "application/zip"
    assert stored["original_name"] == "factura 2026.zip"  # no directories
    on_disk = list(files_dir.rglob("*.zip"))
    assert len(on_disk) == 1 and on_disk[0].read_bytes() == ZIP
    assert ctx["space_id"] in str(on_disk[0])

    body = await save_invoice(client, ctx, payment["id"], file_id=stored["id"])
    assert body["invoice"]["file"]["id"] == stored["id"]

    res = await client.get(f"/api/v1/billing/files/{stored['id']}", headers=ctx["headers"])
    assert res.status_code == 200
    assert res.content == ZIP
    assert res.headers["content-disposition"].startswith("attachment")
    assert res.headers["x-content-type-options"] == "nosniff"
    # A zip never opens in place; a PDF may.
    res = await client.get(
        f"/api/v1/billing/files/{stored['id']}?inline=true", headers=ctx["headers"]
    )
    assert res.headers["content-disposition"].startswith("attachment")
    pdf = await upload(client, ctx, PDF, "acuse.pdf")
    res = await client.get(f"/api/v1/billing/files/{pdf['id']}?inline=true", headers=ctx["headers"])
    assert res.headers["content-disposition"].startswith("inline")

    capture = await upload(client, ctx, JPEG, "captura.jpg")
    res = await client.patch(
        f"/api/v1/billing/payments/{payment['id']}",
        headers=ctx["headers"],
        json={"capture_file_id": capture["id"]},
    )
    assert res.json()["capture_file"]["mime"] == "image/jpeg"


async def test_fac10_rejects_bad_type_empty_and_oversize(client, monkeypatch):
    ctx = await bootstrap_space(client)
    await upload(client, ctx, b"MZ\x90\x00 not allowed", "virus.pdf", expected=422)
    await upload(client, ctx, b"<html><script>", "x.xml", expected=422)
    await upload(client, ctx, b"", "vacio.pdf", expected=422)
    xml = await upload(client, ctx, b'\xef\xbb\xbf<?xml version="1.0"?><cfdi/>', "f.xml")
    assert xml["mime"] == "application/xml"

    from app.services import files as files_svc

    monkeypatch.setattr(files_svc, "MAX_FILE_BYTES", 10)
    await upload(client, ctx, PDF, "grande.pdf", expected=413)


async def test_fac10_files_are_space_scoped(client):
    owner = await bootstrap_space(client)
    stored = await upload(client, owner, PDF, "acuse.pdf")
    stranger = await bootstrap_space(client)
    res = await client.get(f"/api/v1/billing/files/{stored['id']}", headers=stranger["headers"])
    assert res.status_code == 404
    # Nor can a file of another space be attached.
    greenlight = await make_client(client, stranger)
    res = await client.post(
        "/api/v1/billing/payments",
        headers=stranger["headers"],
        json={
            "client_id": greenlight["id"],
            "payment_date": "2026-01-02",
            "amount": "1.00",
            "capture_file_id": stored["id"],
        },
    )
    assert res.status_code == 404


# --- ESP-03 / GLO-05: permissions ---------------------------------------------------------


async def test_fac_permissions_viewer_and_nonmember(client):
    owner = await bootstrap_space(client)
    shared = await client.post("/api/v1/spaces", headers=owner["headers"], json={"name": "Casa"})
    space_id = shared.json()["id"]
    owner_sh = {**owner["headers"], "X-Space-Id": space_id}
    res = await client.post(
        "/api/v1/billing/clients", headers=owner_sh, json={"name": "Greenlight"}
    )
    greenlight = res.json()
    res = await client.post(
        "/api/v1/billing/payments",
        headers=owner_sh,
        json={"client_id": greenlight["id"], "payment_date": "2026-01-02", "amount": "1.00"},
    )
    payment_id = res.json()["id"]

    viewer = await add_member(client, owner["headers"], space_id, "viewer", "viewer@example.com")
    url = f"/api/v1/billing/payments/{payment_id}"
    assert (await client.get(url, headers=viewer)).status_code == 200
    assert (await client.patch(url, headers=viewer, json={"notes": "x"})).status_code == 403
    assert (await client.delete(url, headers=viewer)).status_code == 403
    res = await client.put(
        f"{url}/invoice", headers=viewer, json={"issue_date": "2026-01-02", "total": "1.00"}
    )
    assert res.status_code == 403
    res = await client.post(
        "/api/v1/billing/files?filename=a.pdf",
        headers={**viewer, "Content-Type": "application/octet-stream"},
        content=PDF,
    )
    assert res.status_code == 403
    res = await client.put("/api/v1/billing/settings", headers=viewer, json={})
    assert res.status_code == 403

    stranger = await bootstrap_space(client)
    res = await client.get(url, headers={**stranger["headers"], "X-Space-Id": space_id})
    assert res.status_code == 404
    res = await client.get(url, headers=stranger["headers"])  # own space: not there
    assert res.status_code == 404
