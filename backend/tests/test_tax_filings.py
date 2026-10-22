"""RESICO declarations: FAC-04 (declared/paid), FAC-06 (per period), FAC-07,
FAC-08, FAC-12 and FAC-13.

Mandatory case 22.
"""

import datetime as dt
from decimal import Decimal

import pytest
from freezegun import freeze_time

from app.core.config import settings
from app.services.tax_filings import filing_deadline, isr_estimate
from tests.conftest import bootstrap_space
from tests.test_accounts import add_member
from tests.test_billing import make_client, make_invoiceable, payments, usd_income
from tests.test_wallets import get_account, post_txn


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "files_dir", str(tmp_path / "files"))


async def old_payment(client, ctx, client_id, day, amount, rate, issue_date=None):
    body = {
        "client_id": client_id,
        "payment_date": day,
        "amount": amount,
        "currency": "USD",
        "fiscal_fx_rate": rate,
    }
    if issue_date:
        body["invoice"] = {"issue_date": issue_date, "total": amount, "fx_rate": rate}
    res = await client.post("/api/v1/billing/payments", headers=ctx["headers"], json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def periods(client, ctx):
    res = await client.get("/api/v1/billing/periods", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return {p["period"]: p for p in res.json()}


async def file_declaration(client, ctx, expected=201, **body):
    payload = {"period": "2026-10-01", "filed_date": "2026-11-05", **body}
    res = await client.post("/api/v1/billing/filings", headers=ctx["headers"], json=payload)
    assert res.status_code == expected, res.text
    return res.json()


async def setup(client):
    ctx = await bootstrap_space(client)
    greenlight = await make_client(client, ctx)
    await make_invoiceable(client, ctx, ctx["accounts"]["Dólares"]["id"], greenlight["id"])
    res = await client.put(
        "/api/v1/billing/settings", headers=ctx["headers"], json={"rfc_extra_days": 3}
    )
    assert res.json()["rfc_extra_days"] == 3
    return ctx, greenlight


# --- Pure helpers (FAC-07/12) ----------------------------------------------------------------


def test_fac12_deadline_business_days_and_rfc_digit():
    d = dt.date
    # Sep 2026: the 17th of Oct is a Saturday → Mon 19, + 3 days → Thu 22.
    assert filing_deadline(d(2026, 9, 1), 3) == d(2026, 10, 22)
    assert filing_deadline(d(2026, 9, 1), 0) == d(2026, 10, 19)
    # Oct 2026: Tue Nov 17; Mon 16 (Revolución) doesn't matter; + 3 → Fri 20.
    assert filing_deadline(d(2026, 10, 1), 0) == d(2026, 11, 17)
    assert filing_deadline(d(2026, 10, 1), 3) == d(2026, 11, 20)
    # Feb 2025: Mon Mar 17 was a holiday (Benito Juárez) → Tue 18.
    assert filing_deadline(d(2025, 2, 1), 0) == d(2025, 3, 18)
    # Dec 2026 → Jan 2027: Sun 17 → Mon 18.
    assert filing_deadline(d(2026, 12, 1), 0) == d(2027, 1, 18)


def test_fac07_resico_table():
    assert isr_estimate(Decimal("1896")) == (Decimal("0.0100"), Decimal("19"))
    assert isr_estimate(Decimal("25000")) == (Decimal("0.0100"), Decimal("250"))
    assert isr_estimate(Decimal("30000")) == (Decimal("0.0110"), Decimal("330"))
    assert isr_estimate(Decimal("100000")) == (Decimal("0.0200"), Decimal("2000"))
    assert isr_estimate(Decimal("400000")) == (Decimal("0.0250"), Decimal("10000"))


# --- Mandatory case 22: FAC-06/07/08/12/13 ----------------------------------------------------


@freeze_time("2026-11-05 12:00:00")
async def test_fac_mandatory_case_22(client):
    ctx, greenlight = await setup(client)
    # The guide's October: Sep 25 payment invoiced on Oct 7; Oct 2 payment
    # invoiced the same day.
    sep = await old_payment(
        client, ctx, greenlight["id"], "2026-09-25", "108.33", "17.5030", "2026-10-07"
    )
    await post_txn(client, ctx, **usd_income(ctx, "325.00", "2026-10-02"))
    [oct_payment] = [p for p in await payments(client, ctx) if p["period"] == "2026-10-01"]
    await client.patch(
        f"/api/v1/billing/payments/{oct_payment['id']}",
        headers=ctx["headers"],
        json={"fiscal_fx_rate": "18.0692"},
    )
    res = await client.put(
        f"/api/v1/billing/payments/{oct_payment['id']}/invoice",
        headers=ctx["headers"],
        json={"issue_date": "2026-10-02", "total": "325.00", "fx_rate": "18.0692"},
    )
    assert res.status_code == 200

    by_period = await periods(client, ctx)
    october, september = by_period["2026-10-01"], by_period["2026-09-01"]
    # FAC-06/07: Oct declares 5,872 (not 7,769) and estimates 1% ISR.
    assert october["to_declare"] == "5872"
    assert october["isr_estimate"] == "59"
    assert october["isr_rate"] == "0.0100"
    # FAC-08: the SAT prefills both invoices issued in October; exclude Sep's.
    assert october["sat_prefill"] == "7769"
    assert [i["payment_id"] for i in october["exclude_from_prefill"]] == [sep["id"]]
    assert september["to_declare"] == "1896"
    assert september["sat_prefill"] == "0"
    assert [i["payment_id"] for i in september["add_to_prefill"]] == [sep["id"]]
    # FAC-12: Sep was due Oct 22 (RFC +3) and has no acuse ⇒ overdue.
    assert september["status"] == "to_declare" and september["is_overdue"] is True
    assert september["deadline"] == "2026-10-22"
    assert october["status"] == "to_declare" and october["is_overdue"] is False
    assert october["deadline"] == "2026-11-20"

    # September, already declared and paid outside the app (old period).
    await file_declaration(
        client,
        ctx,
        period="2026-09-01",
        filed_date="2026-10-20",
        operation_number="261710268474",
        declared_income="1896.00",
        isr_amount="19.00",
        amount_due="19.00",
        payment={"paid_date": "2026-10-21", "paid_amount": "19.00"},
    )
    assert (await periods(client, ctx))["2026-09-01"]["status"] == "paid"
    assert {p["id"]: p["status"] for p in await payments(client, ctx)}[sep["id"]] == "paid"
    # A second normal declaration for September ⇒ 409; a complementary one is fine.
    await file_declaration(client, ctx, expected=409, period="2026-09-15", filed_date="2026-11-01")

    # October: acuse with 59 to pay ⇒ to_pay, its payments are "declared".
    filing = await file_declaration(
        client, ctx, isr_amount="59.00", amount_due="59.00", valid_until="2026-11-20"
    )
    october = (await periods(client, ctx))["2026-10-01"]
    assert october["status"] == "to_pay"
    assert october["payment_deadline"] == "2026-11-20"
    assert {p["id"]: p["status"] for p in await payments(client, ctx)}[
        oct_payment["id"]
    ] == "declared"

    # FAC-13: paying from the debit account creates the "Impuestos" expense.
    debit = ctx["accounts"]["Débito"]["id"]
    before = (await get_account(client, ctx, debit))["balance"]
    res = await client.put(
        f"/api/v1/billing/filings/{filing['id']}/payment",
        headers=ctx["headers"],
        json={"paid_date": "2026-11-05", "paid_amount": "59.00", "account_id": debit},
    )
    assert res.status_code == 200, res.text
    expense_id = res.json()["expense_transaction_id"]
    expense = (
        await client.get(f"/api/v1/transactions/{expense_id}", headers=ctx["headers"])
    ).json()
    assert expense["amount"] == "59.00" and expense["type"] == "expense"
    cats = (await client.get("/api/v1/catalogs/categories", headers=ctx["headers"])).json()
    assert {c["id"]: c["name"] for c in cats}[expense["category_id"]] == "Impuestos"
    after = (await get_account(client, ctx, debit))["balance"]
    assert Decimal(before) - Decimal(after) == Decimal("59.00")
    assert (await periods(client, ctx))["2026-10-01"]["status"] == "paid"

    # Removing the payment removes its expense.
    res = await client.delete(
        f"/api/v1/billing/filings/{filing['id']}/payment", headers=ctx["headers"]
    )
    assert res.status_code == 200 and res.json()["paid_date"] is None
    res = await client.get(f"/api/v1/transactions/{expense_id}", headers=ctx["headers"])
    assert res.status_code == 404
    assert (await periods(client, ctx))["2026-10-01"]["status"] == "to_pay"


@freeze_time("2026-11-05 12:00:00")
async def test_fac12_rules_for_filings(client):
    ctx, greenlight = await setup(client)
    await old_payment(client, ctx, greenlight["id"], "2026-10-02", "325.00", "18.0692")
    # The running month can't be declared yet; nor a future filing date.
    await file_declaration(client, ctx, expected=422, period="2026-11-01")
    await file_declaration(client, ctx, expected=422, filed_date="2026-11-06")
    # A zero declaration settles the month without a payment.
    zero = await file_declaration(client, ctx)
    assert (await periods(client, ctx))["2026-10-01"]["status"] == "paid"
    # The payment can't predate the filing.
    res = await client.put(
        f"/api/v1/billing/filings/{zero['id']}/payment",
        headers=ctx["headers"],
        json={"paid_date": "2026-11-01", "paid_amount": "1.00"},
    )
    assert res.status_code == 422
    res = await client.put(
        f"/api/v1/billing/filings/{zero['id']}/payment",
        headers=ctx["headers"],
        json={"paid_date": "2026-11-05", "paid_amount": "1.00"},
    )
    assert res.status_code == 200
    # A paid filing isn't deleted until its payment is removed.
    url = f"/api/v1/billing/filings/{zero['id']}"
    assert (await client.delete(url, headers=ctx["headers"])).status_code == 422
    await client.delete(f"{url}/payment", headers=ctx["headers"])
    assert (await client.delete(url, headers=ctx["headers"])).status_code == 204
    # FAC-13: a USD account can't hold the MXN tax expense (TAR-10).
    filing = await file_declaration(client, ctx, amount_due="59.00")
    res = await client.put(
        f"/api/v1/billing/filings/{filing['id']}/payment",
        headers=ctx["headers"],
        json={
            "paid_date": "2026-11-05",
            "paid_amount": "59.00",
            "account_id": ctx["accounts"]["Dólares"]["id"],
        },
    )
    assert res.status_code == 422
    assert (await periods(client, ctx))["2026-10-01"]["status"] == "to_pay"  # atomic


@freeze_time("2026-11-05 12:00:00")
async def test_fac13_deleting_tax_expense_unlinks_it(client):
    ctx, greenlight = await setup(client)
    await old_payment(client, ctx, greenlight["id"], "2026-10-02", "325.00", "18.0692")
    filing = await file_declaration(client, ctx, amount_due="59.00")
    res = await client.put(
        f"/api/v1/billing/filings/{filing['id']}/payment",
        headers=ctx["headers"],
        json={
            "paid_date": "2026-11-05",
            "paid_amount": "59.00",
            "account_id": ctx["accounts"]["Débito"]["id"],
        },
    )
    expense_id = res.json()["expense_transaction_id"]
    res = await client.delete(f"/api/v1/transactions/{expense_id}", headers=ctx["headers"])
    assert res.status_code == 204
    october = (await periods(client, ctx))["2026-10-01"]
    assert october["status"] == "paid"  # the payment record stays
    assert october["filings"][0]["expense_transaction_id"] is None


@freeze_time("2026-11-05 12:00:00")
async def test_fac_filing_permissions(client):
    owner = await bootstrap_space(client)
    shared = await client.post("/api/v1/spaces", headers=owner["headers"], json={"name": "Casa"})
    space_id = shared.json()["id"]
    owner_sh = {**owner["headers"], "X-Space-Id": space_id}
    res = await client.post(
        "/api/v1/billing/filings",
        headers=owner_sh,
        json={"period": "2026-10-01", "filed_date": "2026-11-05"},
    )
    filing_id = res.json()["id"]
    viewer = await add_member(client, owner["headers"], space_id, "viewer", "viewer@example.com")
    assert (await client.get("/api/v1/billing/periods", headers=viewer)).status_code == 200
    url = f"/api/v1/billing/filings/{filing_id}"
    assert (await client.patch(url, headers=viewer, json={"notes": "x"})).status_code == 403
    assert (await client.delete(url, headers=viewer)).status_code == 403
    res = await client.put(
        f"{url}/payment", headers=viewer, json={"paid_date": "2026-11-05", "paid_amount": "1.00"}
    )
    assert res.status_code == 403
    stranger = await bootstrap_space(client)
    res = await client.patch(url, headers=stranger["headers"], json={"notes": "x"})
    assert res.status_code == 404
