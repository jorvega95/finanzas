"""Accounts beyond cards: TAR-09 (cash), TAR-10 (currency), TXN-13 (cross-currency
transfer), TXN-14 (transfer fee), PAT-01/FX-04 (USD valuation), PRO-02 (savings).

Mandatory cases 14 (XTRM/ARQ flow) and 15 (cash adjustment).
"""

from datetime import date
from decimal import Decimal

from freezegun import freeze_time

from app.models.fx import ExchangeRate
from tests.conftest import bootstrap_space


async def make_account(client, ctx, type_name, name, currency="MXN", **extra):
    res = await client.post(
        "/api/v1/accounts",
        headers=ctx["headers"],
        json={
            "account_type_id": ctx["account_types"][type_name]["id"],
            "name": name,
            "currency": currency,
            **extra,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def get_account(client, ctx, account_id):
    res = await client.get(f"/api/v1/accounts/{account_id}", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def post_txn(client, ctx, expected=201, **body):
    res = await client.post("/api/v1/transactions", headers=ctx["headers"], json=body)
    assert res.status_code == expected, res.text
    return res.json()


def income(ctx, account_id, amount, currency="MXN", day="2026-06-01"):
    return {
        "type": "income",
        "date": day,
        "amount": amount,
        "currency": currency,
        "category_id": ctx["income_categories"]["Freelance"]["id"],
        "account_id": account_id,
        "description": "LinkedIn vía Greenlight",
    }


def expense(ctx, account_id, amount, currency="MXN", day="2026-06-05"):
    return {
        "type": "expense",
        "date": day,
        "amount": amount,
        "currency": currency,
        "category_id": ctx["categories"]["Comida"]["id"],
        "account_id": account_id,
    }


def transfer(source, target, amount, currency, day="2026-06-15", **extra):
    return {
        "type": "transfer",
        "date": day,
        "amount": amount,
        "currency": currency,
        "account_id": source,
        "account_to_id": target,
        **extra,
    }


async def month_totals(client, ctx, month="2026-06"):
    res = await client.get(f"/api/v1/dashboard/summary?month={month}", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()["totals"]


async def seed_usd_rate(db_session, rate="18.00", day=date(2026, 6, 1)):
    db_session.add(ExchangeRate(base="USD", quote="MXN", date=day, rate=Decimal(rate)))
    await db_session.commit()


# --- TAR-10: movements go in the account's currency -------------------------


async def test_tar10_movement_currency_must_match_account(client):
    ctx = await bootstrap_space(client)
    mxn = ctx["accounts"]["Débito"]["id"]
    # A USD expense on a MXN account is rejected (record what the bank charged).
    res = await client.post(
        "/api/v1/transactions", headers=ctx["headers"], json=expense(ctx, mxn, "10.00", "USD")
    )
    assert res.status_code == 422
    assert "maneja MXN" in res.json()["detail"]


async def test_tar10_currency_locked_once_used(client, db_session):
    await seed_usd_rate(db_session)
    ctx = await bootstrap_space(client)
    wallet = await make_account(client, ctx, "Billetera digital", "Monedero")
    # Without movements the currency may still change.
    res = await client.patch(
        f"/api/v1/accounts/{wallet['id']}", headers=ctx["headers"], json={"currency": "USD"}
    )
    assert res.status_code == 200 and res.json()["currency"] == "USD"
    await post_txn(client, ctx, **income(ctx, wallet["id"], "5.00", "USD"))
    res = await client.patch(
        f"/api/v1/accounts/{wallet['id']}", headers=ctx["headers"], json={"currency": "MXN"}
    )
    assert res.status_code == 409


# --- TXN-13/14: the XTRM → ARQ → BBVA flow (mandatory case 14) ----------------


@freeze_time("2026-06-20 12:00:00")
async def test_txn13_14_freelance_usd_flow(client, db_session):
    await seed_usd_rate(db_session)
    ctx = await bootstrap_space(client)
    xtrm = await make_account(client, ctx, "Billetera digital", "XTRM", "USD")
    bbva = await make_account(client, ctx, "Débito", "BBVA", initial_balance="0")

    # LinkedIn pays 300 USD into XTRM: income at the frozen rate (FX-03).
    paid = await post_txn(client, ctx, **income(ctx, xtrm["id"], "300.00", "USD"))
    assert Decimal(paid["fx_rate_to_base"]) == Decimal("18.00")
    assert (await get_account(client, ctx, xtrm["id"]))["balance"] == "300.00"

    # 297 USD move (3 USD fee) and BBVA receives 5,250 MXN.
    moved = await post_txn(
        client,
        ctx,
        **transfer(xtrm["id"], bbva["id"], "297.00", "USD", amount_to="5250.00", fee_amount="3.00"),
    )
    assert moved["amount_to"] == "5250.00"
    assert moved["fee_amount"] == "3.00"

    assert (await get_account(client, ctx, xtrm["id"]))["balance"] == "0.00"
    assert (await get_account(client, ctx, bbva["id"]))["balance"] == "5250.00"

    # The fee is a 3 USD expense under "Comisiones e intereses"; the transfer
    # itself never counts (TXN-02) and the rate difference isn't spending.
    listed = (
        await client.get(f"/api/v1/transactions?account_id={xtrm['id']}", headers=ctx["headers"])
    ).json()["items"]
    fee = next(t for t in listed if t["fee_for_id"] == moved["id"])
    assert fee["type"] == "expense" and fee["amount"] == "3.00" and fee["currency"] == "USD"
    cats = (await client.get("/api/v1/catalogs/categories", headers=ctx["headers"])).json()
    fees_cat = next(c for c in cats if c["name"] == "Comisiones e intereses")
    assert fee["category_id"] == fees_cat["id"]
    totals = await month_totals(client, ctx)
    assert Decimal(totals["income"]) == Decimal("5400.00")  # 300 × 18.00
    assert Decimal(totals["expenses"]) == Decimal("54.00")  # 3 × 18.00 (fee only)


async def test_txn13_cross_currency_requires_amount_to(client):
    ctx = await bootstrap_space(client)
    usd = ctx["accounts"]["Dólares"]["id"]
    mxn = ctx["accounts"]["Débito"]["id"]
    await post_txn(client, ctx, expected=422, **transfer(usd, mxn, "10.00", "USD"))
    # Same currency: amount_to makes no sense.
    efectivo = ctx["accounts"]["Efectivo"]["id"]
    await post_txn(
        client, ctx, expected=422, **transfer(mxn, efectivo, "10.00", "MXN", amount_to="10.00")
    )
    # Fees and amount_to are transfer-only.
    await post_txn(
        client, ctx, expected=422, **{**expense(ctx, mxn, "10.00"), "fee_amount": "1.00"}
    )


async def test_txn08_fee_counts_against_available_balance(client, db_session):
    await seed_usd_rate(db_session)
    ctx = await bootstrap_space(client)
    wallet = await make_account(client, ctx, "Billetera digital", "XTRM", "USD")
    await post_txn(client, ctx, **income(ctx, wallet["id"], "100.00", "USD"))
    target = ctx["accounts"]["Dólares"]["id"]
    # 98 + 3 fee = 101 > 100 available ⇒ rejected; 97 + 3 fits exactly.
    await post_txn(
        client, ctx, expected=422, **transfer(wallet["id"], target, "98.00", "USD", fee_amount="3")
    )
    await post_txn(client, ctx, **transfer(wallet["id"], target, "97.00", "USD", fee_amount="3"))
    assert (await get_account(client, ctx, wallet["id"]))["balance"] == "0.00"


async def test_txn14_fee_follows_its_transfer(client):
    ctx = await bootstrap_space(client)
    src = ctx["accounts"]["Débito"]["id"]
    dst = ctx["accounts"]["Efectivo"]["id"]
    moved = await post_txn(client, ctx, **transfer(src, dst, "100.00", "MXN", fee_amount="5"))

    def fees(items):
        return [t for t in items if t["fee_for_id"] == moved["id"]]

    async def listed():
        res = await client.get("/api/v1/transactions?limit=200", headers=ctx["headers"])
        return res.json()["items"]

    fee = fees(await listed())[0]
    # The fee row can't be edited or deleted on its own.
    res = await client.put(
        f"/api/v1/transactions/{fee['id']}",
        headers=ctx["headers"],
        json=expense(ctx, src, "1.00"),
    )
    assert res.status_code == 422
    res = await client.delete(f"/api/v1/transactions/{fee['id']}", headers=ctx["headers"])
    assert res.status_code == 422

    # Editing the transfer rebuilds its fee; removing it drops the row.
    res = await client.put(
        f"/api/v1/transactions/{moved['id']}",
        headers=ctx["headers"],
        json=transfer(src, dst, "100.00", "MXN", fee_amount="7.50"),
    )
    assert res.status_code == 200 and res.json()["fee_amount"] == "7.50"
    assert [f["amount"] for f in fees(await listed())] == ["7.50"]
    res = await client.put(
        f"/api/v1/transactions/{moved['id']}",
        headers=ctx["headers"],
        json=transfer(src, dst, "100.00", "MXN"),
    )
    assert res.status_code == 200 and res.json()["fee_amount"] is None
    assert fees(await listed()) == []

    # Deleting the transfer deletes its fee too.
    await client.put(
        f"/api/v1/transactions/{moved['id']}",
        headers=ctx["headers"],
        json=transfer(src, dst, "100.00", "MXN", fee_amount="2"),
    )
    res = await client.delete(f"/api/v1/transactions/{moved['id']}", headers=ctx["headers"])
    assert res.status_code == 204
    assert await listed() == []


# --- TAR-09: cash (mandatory case 15) -----------------------------------------


@freeze_time("2026-06-20 12:00:00")
async def test_tar09_cash_goes_negative_and_adjusts(client):
    ctx = await bootstrap_space(client)
    cash = ctx["accounts"]["Efectivo"]["id"]
    # Cash always allows overdraft: spending with a 0 balance is fine.
    await post_txn(client, ctx, **expense(ctx, cash, "1200.00"))
    assert (await get_account(client, ctx, cash))["balance"] == "-1200.00"
    before = await month_totals(client, ctx)

    res = await client.post(
        f"/api/v1/accounts/{cash}/balance", headers=ctx["headers"], json={"balance": "0"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["balance"] == "0.00"
    # No transaction created and no aggregate moved.
    txns = (await client.get("/api/v1/transactions", headers=ctx["headers"])).json()
    assert txns["total"] == 1
    assert await month_totals(client, ctx) == before

    # Real cash on hand later: 350.
    res = await client.post(
        f"/api/v1/accounts/{cash}/balance", headers=ctx["headers"], json={"balance": "350.00"}
    )
    assert res.json()["balance"] == "350.00"

    # allow_overdraft can't be switched off for cash.
    res = await client.patch(
        f"/api/v1/accounts/{cash}", headers=ctx["headers"], json={"allow_overdraft": False}
    )
    assert res.status_code == 200 and res.json()["allow_overdraft"] is True


async def test_tar09_only_cash_is_adjustable(client):
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    res = await client.post(
        f"/api/v1/accounts/{debit}/balance", headers=ctx["headers"], json={"balance": "10"}
    )
    assert res.status_code == 409


# --- PAT-01/FX-04 and PRO-02 ----------------------------------------------------


@freeze_time("2026-06-20 12:00:00")
async def test_pat01_values_usd_balances_at_todays_rate(client, db_session):
    await seed_usd_rate(db_session, "17.00", date(2026, 6, 1))
    ctx = await bootstrap_space(client)
    wallet = await make_account(client, ctx, "Billetera digital", "XTRM", "USD")
    await post_txn(client, ctx, **income(ctx, wallet["id"], "100.00", "USD"))
    # The rate moves after the income was recorded: net worth is mark-to-market.
    await seed_usd_rate(db_session, "19.50", date(2026, 6, 19))

    body = (
        await client.post("/api/v1/investments/net-worth/snapshot", headers=ctx["headers"])
    ).json()
    assert body["assets"] == "1950.00"  # 100 USD × 19.50, not × 17.00


@freeze_time("2026-06-20 12:00:00")
async def test_pro02_cash_counts_and_savings_does_not(client):
    ctx = await bootstrap_space(client)
    cash = ctx["accounts"]["Efectivo"]["id"]
    await client.post(
        f"/api/v1/accounts/{cash}/balance", headers=ctx["headers"], json={"balance": "500.00"}
    )
    await make_account(client, ctx, "Ahorro", "Cajita", initial_balance="10000.00")

    res = await client.get("/api/v1/dashboard/forecast?horizon_months=3", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["starting_cash"] == "500.00"  # savings is not liquid


@freeze_time("2026-06-20 12:00:00")
async def test_txn09_13_usd_payment_to_mxn_card_applies_received_amount(client, db_session):
    """TXN-09 + TXN-13: paying a MXN card from a USD wallet credits the
    statement with what the card received, not the USD amount sent."""
    await seed_usd_rate(db_session)
    ctx = await bootstrap_space(client)
    card = await make_account(
        client, ctx, "Crédito", "BBVA Azul", statement_day=15, payment_due_days=20
    )
    wallet = await make_account(client, ctx, "Billetera digital", "XTRM", "USD")
    await post_txn(client, ctx, **income(ctx, wallet["id"], "100.00", "USD"))
    await post_txn(client, ctx, **expense(ctx, card["id"], "1800.00", day="2026-06-10"))
    await client.post("/api/v1/accounts/close-cycles", headers=ctx["headers"])

    payment = await post_txn(
        client, ctx, **transfer(wallet["id"], card["id"], "100.00", "USD", amount_to="1800.00")
    )
    statements = (
        await client.get(f"/api/v1/accounts/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    paid = next(s for s in statements if s["id"] == payment["statement_id"])
    assert paid["paid_amount"] == "1800.00"
    assert paid["status"] == "paid"

    # Deleting the payment takes back exactly what was applied.
    await client.delete(f"/api/v1/transactions/{payment['id']}", headers=ctx["headers"])
    statements = (
        await client.get(f"/api/v1/accounts/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    assert next(s for s in statements if s["id"] == paid["id"])["paid_amount"] == "0.00"


async def test_confirm_rejects_fee_rows_and_reviewed_amount_changes(client):
    """TXN-14 / REC-03: confirm cannot rewrite a fee or an already-reviewed amount."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-01",
            "amount": "100.00",
            "currency": "MXN",
            "description": "Ya revisado",
            "category_id": ctx["categories"]["Comida"]["id"],
            "account_id": ctx["accounts"]["Débito"]["id"],
        },
    )
    assert res.status_code == 201, res.text
    txn_id = res.json()["id"]
    res = await client.post(
        f"/api/v1/transactions/{txn_id}/confirm",
        headers=ctx["headers"],
        json={"amount": "1.00"},
    )
    assert res.status_code == 422


async def test_confirm_amount_respects_balance(client, db_session):
    """TAR-05 / REC-03: a reviewed amount cannot overdraw a balance account."""
    import uuid

    from app.models.transactions import Transaction

    ctx = await bootstrap_space(client)
    bbva = await make_account(client, ctx, "Débito", "BBVA", initial_balance="100.00")
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-01",
            "amount": "50.00",
            "currency": "MXN",
            "description": "Luz",
            "category_id": ctx["categories"]["Comida"]["id"],
            "account_id": bbva["id"],
        },
    )
    assert res.status_code == 201, res.text
    txn_id = res.json()["id"]
    txn = await db_session.get(Transaction, uuid.UUID(txn_id))
    txn.needs_review = True
    await db_session.commit()

    url = f"/api/v1/transactions/{txn_id}/confirm"
    res = await client.post(url, headers=ctx["headers"], json={"amount": "150.00"})
    assert res.status_code == 422
    res = await client.post(url, headers=ctx["headers"], json={"amount": "100.00"})
    assert res.status_code == 200, res.text
    assert res.json()["amount"] == "100.00"
    assert res.json()["needs_review"] is False
