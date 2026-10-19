"""Personal loans: TAR-11 (behavior `loan`), CAT-02 ("Regalos recibidos"),
PAT-01 (loans in net worth) and PRO-02 (loans are not liquid).

Mandatory case 16.
"""

from freezegun import freeze_time

from tests.conftest import bootstrap_space
from tests.test_msi import make_plan
from tests.test_wallets import (
    get_account,
    make_account,
    month_totals,
    post_txn,
    transfer,
)


async def make_loan(client, ctx, name="Préstamo papás", **extra):
    return await make_account(client, ctx, "Préstamo personal", name, **extra)


def gift(ctx, account_id, amount, day="2026-06-18"):
    return {
        "type": "income",
        "date": day,
        "amount": amount,
        "currency": "MXN",
        "category_id": ctx["income_categories"]["Regalos recibidos"]["id"],
        "account_id": account_id,
        "description": "Condonación",
    }


# --- CAT-02 / CAT-08 seeds ---------------------------------------------------------


async def test_cat02_seeds_loan_type_and_gift_income_category(client):
    ctx = await bootstrap_space(client)
    assert ctx["account_types"]["Préstamo personal"]["behavior"] == "loan"
    assert "Regalos recibidos" in ctx["income_categories"]
    # The expense "Regalos" (gifts you give) is still there and distinct.
    assert "Regalos" in ctx["expense_categories"]


# --- TAR-11: mandatory case 16 -----------------------------------------------------


@freeze_time("2026-06-20 12:00:00")
async def test_tar11_loan_flow_mandatory_case_16(client):
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    loan = await make_loan(client, ctx)
    loan = await get_account(client, ctx, loan["id"])
    assert loan["behavior"] == "loan"
    assert loan["balance"] == "0.00"
    assert loan["allow_overdraft"] is True  # always, like cash

    # Receiving the borrowed money: a transfer, not income (TXN-02).
    await post_txn(client, ctx, **transfer(loan["id"], debit, "10000.00", "MXN", day="2026-06-02"))
    assert (await get_account(client, ctx, loan["id"]))["balance"] == "-10000.00"
    assert (await get_account(client, ctx, debit))["balance"] == "10000.00"
    totals = await month_totals(client, ctx)
    assert totals["income"] == "0.00"

    # The lender pays the band directly: the debt grows and it is an expense.
    await post_txn(
        client,
        ctx,
        type="expense",
        date="2026-06-05",
        amount="30000.00",
        currency="MXN",
        category_id=ctx["categories"]["Entretenimiento"]["id"],
        account_id=loan["id"],
        description="Banda",
    )
    assert (await get_account(client, ctx, loan["id"]))["balance"] == "-40000.00"
    assert (await month_totals(client, ctx))["expenses"] == "30000.00"

    # Paying it back: a transfer, not an expense.
    await post_txn(client, ctx, **transfer(debit, loan["id"], "15000.00", "MXN", day="2026-06-10"))
    assert (await get_account(client, ctx, loan["id"]))["balance"] == "-25000.00"
    assert (await month_totals(client, ctx))["expenses"] == "30000.00"

    # Forgiveness: income on the loan account, no cash moves.
    await post_txn(client, ctx, **gift(ctx, loan["id"], "5000.00"))
    loan_now = await get_account(client, ctx, loan["id"])
    assert loan_now["balance"] == "-20000.00"
    assert loan_now["signed_balance"] == "-20000.00"  # TAR-06: a liability
    assert (await month_totals(client, ctx))["income"] == "5000.00"
    assert (await get_account(client, ctx, debit))["balance"] == "-5000.00"

    # PAT-01: the debt is a liability, not a negative asset.
    snap = (
        await client.post("/api/v1/investments/net-worth/snapshot", headers=ctx["headers"])
    ).json()
    assert snap["liabilities"] == "20000.00"
    assert snap["assets"] == "-5000.00"  # only the overdrawn debit
    assert snap["net_worth"] == "-25000.00"

    # PRO-02: the loan is not liquid.
    res = await client.get("/api/v1/dashboard/forecast?horizon_months=3", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["starting_cash"] == "-5000.00"


@freeze_time("2026-06-20 12:00:00")
async def test_tar11_initial_debt_and_receivable(client):
    """`initial_balance` is signed: negative = you owe, positive = they owe you."""
    ctx = await bootstrap_space(client)
    owed = await make_loan(client, ctx, initial_balance="-8000.00")
    lent = await make_loan(client, ctx, name="Préstamo a Luis", initial_balance="3000.00")
    assert (await get_account(client, ctx, owed["id"]))["balance"] == "-8000.00"
    assert (await get_account(client, ctx, lent["id"]))["balance"] == "3000.00"

    snap = (
        await client.post("/api/v1/investments/net-worth/snapshot", headers=ctx["headers"])
    ).json()
    assert snap["liabilities"] == "8000.00"
    assert snap["assets"] == "3000.00"  # a receivable is an asset


async def test_tar11_overpaying_flips_to_receivable(client):
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    loan = await make_loan(client, ctx, initial_balance="-1000.00")
    await post_txn(client, ctx, **transfer(debit, loan["id"], "1500.00", "MXN"))
    assert (await get_account(client, ctx, loan["id"]))["balance"] == "500.00"


async def test_tar11_overdraft_is_always_allowed(client):
    """A loan never rejects a movement for lack of balance (TAR-05, TXN-08)."""
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    loan = await make_loan(client, ctx, allow_overdraft=False)
    assert loan["allow_overdraft"] is True
    res = await client.patch(
        f"/api/v1/accounts/{loan['id']}",
        headers=ctx["headers"],
        json={"allow_overdraft": False},
    )
    assert res.status_code == 200 and res.json()["allow_overdraft"] is True
    await post_txn(client, ctx, **transfer(loan["id"], debit, "500.00", "MXN"))


async def test_tar11_rejects_credit_fields_and_manual_adjustment(client):
    ctx = await bootstrap_space(client)
    # Only a loan may open with a negative balance (TAR-05).
    res = await client.post(
        "/api/v1/accounts",
        headers=ctx["headers"],
        json={
            "account_type_id": ctx["account_types"]["Débito"]["id"],
            "name": "Negativa",
            "initial_balance": "-1.00",
        },
    )
    assert res.status_code == 422
    res = await client.post(
        "/api/v1/accounts",
        headers=ctx["headers"],
        json={
            "account_type_id": ctx["account_types"]["Préstamo personal"]["id"],
            "name": "Con corte",
            "statement_day": 10,
        },
    )
    assert res.status_code == 422
    loan = await make_loan(client, ctx)
    # TAR-09: only cash is adjusted by hand; a loan squares up with movements.
    res = await client.post(
        f"/api/v1/accounts/{loan['id']}/balance",
        headers=ctx["headers"],
        json={"balance": "0.00"},
    )
    assert res.status_code == 409


async def test_tar11_rejects_msi(client):
    """MSI-01: installment plans only exist on credit accounts."""
    ctx = await bootstrap_space(client)
    loan = await make_loan(client, ctx)
    purchase = await post_txn(
        client,
        ctx,
        type="expense",
        date="2026-06-05",
        amount="1200.00",
        currency="MXN",
        category_id=ctx["categories"]["Ropa"]["id"],
        account_id=loan["id"],
    )
    await make_plan(client, ctx, purchase["id"], 3, expected=422)


@freeze_time("2026-06-20 12:00:00")
async def test_pro03_loan_movements_in_forecast(client):
    """PRO-03/TAR-11: what the lender pays directly and forgiveness are not cash
    flow; a future repayment from a liquid account is an outflow and receiving
    the borrowed money is an inflow."""
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    loan = await make_loan(client, ctx, initial_balance="-20000.00")
    await post_txn(
        client,
        ctx,
        type="expense",
        date="2026-07-01",
        amount="9000.00",
        currency="MXN",
        category_id=ctx["categories"]["Entretenimiento"]["id"],
        account_id=loan["id"],
        description="Banda",
    )
    await post_txn(client, ctx, **gift(ctx, loan["id"], "1000.00", day="2026-07-02"))
    await post_txn(
        client,
        ctx,
        **transfer(debit, loan["id"], "5000.00", "MXN", day="2026-07-15", description="Abono"),
    )
    await post_txn(client, ctx, **transfer(loan["id"], debit, "2000.00", "MXN", day="2026-07-20"))

    res = await client.get("/api/v1/dashboard/forecast?horizon_months=3", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    events = [(e["kind"], e["direction"], e["amount"]) for e in res.json()["events"]]
    assert events == [("loan_out", "out", "5000.00"), ("loan_in", "in", "2000.00")]
