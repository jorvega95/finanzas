"""Events: EVT-01..EVT-05 (grouping, summary, dashboard/budget toggle).

Mandatory case 17.
"""

from freezegun import freeze_time

from tests.conftest import bootstrap_space
from tests.test_accounts import add_member, close_cycles, create_card
from tests.test_msi import make_plan
from tests.test_wallets import make_account, post_txn, transfer


async def make_event(client, ctx, name="Boda", expected=201, **extra):
    res = await client.post("/api/v1/events", headers=ctx["headers"], json={"name": name, **extra})
    assert res.status_code == expected, res.text
    return res.json()


async def get_summary(client, ctx, event_id):
    res = await client.get(f"/api/v1/events/{event_id}", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


def expense(ctx, account_id, amount, category="Comida", day="2026-06-05", **extra):
    return {
        "type": "expense",
        "date": day,
        "amount": amount,
        "currency": "MXN",
        "category_id": ctx["expense_categories"][category]["id"],
        "account_id": account_id,
        **extra,
    }


def gift(ctx, account_id, amount, day="2026-06-18", **extra):
    return {
        "type": "income",
        "date": day,
        "amount": amount,
        "currency": "MXN",
        "category_id": ctx["income_categories"]["Regalos recibidos"]["id"],
        "account_id": account_id,
        **extra,
    }


async def summary(client, ctx, exclude_events=False, month="2026-06"):
    res = await client.get(
        f"/api/v1/dashboard/summary?month={month}&exclude_events={str(exclude_events).lower()}",
        headers=ctx["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


async def set_event(client, ctx, txn_id, event_id, expected=200):
    res = await client.patch(
        f"/api/v1/transactions/{txn_id}/event",
        headers=ctx["headers"],
        json={"event_id": event_id},
    )
    assert res.status_code == expected, res.text
    return res.json()


# --- Mandatory case 17: EVT-03/04 ----------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_evt03_04_summary_and_toggle_mandatory_case_17(client):
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    card = await create_card(client, ctx)
    boda = await make_event(client, ctx, budget="50000.00")

    await post_txn(
        client, ctx, **expense(ctx, debit, "10000.00", "Entretenimiento", event_id=boda["id"])
    )
    purchase = await post_txn(
        client, ctx, **expense(ctx, card["id"], "12000.00", "Ropa", day="2026-06-10")
    )
    await make_plan(client, ctx, purchase["id"], 12)
    # MSI-08 blocks editing the parent; the event is linked on its own (EVT-02).
    linked = await set_event(client, ctx, purchase["id"], boda["id"])
    assert linked["event_id"] == boda["id"]
    await close_cycles(client, ctx)  # installment 1 charged in the 15-jun statement
    await post_txn(client, ctx, **gift(ctx, debit, "4000.00", event_id=boda["id"]))
    await post_txn(client, ctx, **expense(ctx, debit, "500.00"))  # not in the event

    # EVT-03: the whole MSI purchase, never parent + installments.
    body = await get_summary(client, ctx, boda["id"])
    assert body["spent"] == "22000.00"
    assert body["received"] == "4000.00"
    assert body["net"] == "18000.00"
    assert body["budget_remaining"] == "28000.00"
    by_category = {row["category_name"]: row["total"] for row in body["by_category"]}
    assert by_category == {"Ropa": "12000.00", "Entretenimiento": "10000.00"}

    # EVT-04 off (default): event spending is real spending.
    totals = (await summary(client, ctx))["totals"]
    assert totals["expenses"] == "11500.00"  # 10,000 + installment 1,000 + 500
    assert totals["income"] == "4000.00"
    # EVT-04 on: neither the direct expense, the installment nor the gift.
    off = await summary(client, ctx, exclude_events=True)
    assert off["totals"]["expenses"] == "500.00"
    assert off["totals"]["income"] == "0.00"
    assert [(r["category_name"], r["total"]) for r in off["by_category"]] == [("Comida", "500.00")]
    assert off["trend"][-1]["expenses"] == "500.00"

    # DSH-06 uses the same predicate.
    res = await client.get(
        "/api/v1/dashboard/by-nature/discretionary?month=2026-06&exclude_events=true",
        headers=ctx["headers"],
    )
    assert res.json()["total"] == "0.00"
    res = await client.get(
        "/api/v1/dashboard/by-nature/discretionary?month=2026-06", headers=ctx["headers"]
    )
    assert res.json()["total"] == "11000.00"

    # PRE-02 with the toggle.
    res = await client.post(
        "/api/v1/budgets",
        headers=ctx["headers"],
        json={
            "category_id": ctx["expense_categories"]["Entretenimiento"]["id"],
            "month": "2026-06",
            "amount": "20000.00",
        },
    )
    assert res.status_code == 201, res.text
    budgets = (await client.get("/api/v1/budgets?month=2026-06", headers=ctx["headers"])).json()
    assert budgets[0]["consumed"] == "10000.00"
    budgets = (
        await client.get(
            "/api/v1/budgets?month=2026-06&exclude_events=true", headers=ctx["headers"]
        )
    ).json()
    assert budgets[0]["consumed"] == "0.00"


# --- EVT-01: CRUD ---------------------------------------------------------------------


async def test_evt01_crud_unique_name_and_soft_delete(client):
    ctx = await bootstrap_space(client)
    boda = await make_event(client, ctx, date="2027-03-20", notes="Hacienda")
    assert boda["is_active"] is True
    await make_event(client, ctx, name="  BODA ", expected=409)  # CAT-01 style

    res = await client.patch(
        f"/api/v1/events/{boda['id']}", headers=ctx["headers"], json={"budget": "300000.00"}
    )
    assert res.status_code == 200 and res.json()["budget"] == "300000.00"
    assert res.json()["date"] == "2027-03-20"  # untouched

    listing = (await client.get("/api/v1/events", headers=ctx["headers"])).json()
    assert [e["event"]["name"] for e in listing] == ["Boda"]
    assert listing[0]["spent"] == "0.00"

    # GLO-03: with linked movements it can only be deactivated.
    txn = await post_txn(
        client, ctx, **expense(ctx, ctx["accounts"]["Débito"]["id"], "100.00", event_id=boda["id"])
    )
    res = await client.delete(f"/api/v1/events/{boda['id']}", headers=ctx["headers"])
    assert res.status_code == 409
    res = await client.patch(
        f"/api/v1/events/{boda['id']}", headers=ctx["headers"], json={"is_active": False}
    )
    assert res.json()["is_active"] is False
    assert (await client.get("/api/v1/events", headers=ctx["headers"])).json() == []
    listing = (
        await client.get("/api/v1/events?include_inactive=true", headers=ctx["headers"])
    ).json()
    assert len(listing) == 1

    # Without links it is deleted physically.
    await client.delete(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"])
    res = await client.delete(f"/api/v1/events/{boda['id']}", headers=ctx["headers"])
    assert res.status_code == 204


# --- EVT-02: linking rules --------------------------------------------------------------


async def test_evt02_inactive_event_rejects_new_links_but_keeps_existing(client):
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    boda = await make_event(client, ctx)
    txn = await post_txn(client, ctx, **expense(ctx, debit, "100.00", event_id=boda["id"]))
    await client.patch(
        f"/api/v1/events/{boda['id']}", headers=ctx["headers"], json={"is_active": False}
    )
    # New link: rejected.
    await post_txn(client, ctx, expected=422, **expense(ctx, debit, "50.00", event_id=boda["id"]))
    # Editing a transaction already linked keeps its event.
    res = await client.put(
        f"/api/v1/transactions/{txn['id']}",
        headers=ctx["headers"],
        json=expense(ctx, debit, "120.00", event_id=boda["id"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["event_id"] == boda["id"]


async def test_evt02_event_must_belong_to_the_space(client):
    ctx = await bootstrap_space(client)
    other = await bootstrap_space(client)
    foreign = await make_event(client, other)
    await post_txn(
        client,
        ctx,
        expected=422,
        **expense(ctx, ctx["accounts"]["Débito"]["id"], "10.00", event_id=foreign["id"]),
    )


async def test_evt02_transfer_fee_follows_its_transfer(client):
    """TXN-14: the fee row carries the transfer's event and counts as spent;
    the transfer itself never sums (TXN-02)."""
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    loan = await make_account(client, ctx, "Préstamo personal", "Préstamo papás")
    boda = await make_event(client, ctx)
    payment = await post_txn(
        client, ctx, **transfer(debit, loan["id"], "5000.00", "MXN", fee_amount="15.00")
    )
    await set_event(client, ctx, payment["id"], boda["id"])

    body = await get_summary(client, ctx, boda["id"])
    assert body["spent"] == "15.00"  # only the fee
    assert body["movements"] == 2
    assert [(loan["name"], loan["balance"]) for loan in body["loans"]] == [
        ("Préstamo papás", "5000.00")
    ]

    # Unlinking the transfer unlinks its fee too.
    await set_event(client, ctx, payment["id"], None)
    assert (await get_summary(client, ctx, boda["id"]))["movements"] == 0
    # The fee row itself is managed through its transfer.
    fee = (
        await client.get(f"/api/v1/transactions?event_id={boda['id']}", headers=ctx["headers"])
    ).json()
    assert fee["total"] == 0


@freeze_time("2026-06-20 18:00:00")
async def test_evt02_msi_settlement_stays_in_the_event(client):
    """MSI-07: the early-settlement charge inherits the parent's event, so the
    event's total cost doesn't change."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    boda = await make_event(client, ctx)
    purchase = await post_txn(
        client,
        ctx,
        **expense(ctx, card["id"], "12000.00", "Ropa", day="2026-06-10", event_id=boda["id"]),
    )
    plan = await make_plan(client, ctx, purchase["id"], 12)
    await close_cycles(client, ctx)
    res = await client.post(
        f"/api/v1/installment-plans/{plan['id']}/settle", headers=ctx["headers"]
    )
    assert res.status_code == 200, res.text
    assert (await get_summary(client, ctx, boda["id"]))["spent"] == "12000.00"
    off = await summary(client, ctx, exclude_events=True)
    assert off["totals"]["expenses"] == "0.00"


# --- EVT-05: listing filter ---------------------------------------------------------------


async def test_evt05_transactions_filter_by_event(client):
    ctx = await bootstrap_space(client)
    debit = ctx["accounts"]["Débito"]["id"]
    boda = await make_event(client, ctx)
    mine = await post_txn(client, ctx, **expense(ctx, debit, "10.00", event_id=boda["id"]))
    await post_txn(client, ctx, **expense(ctx, debit, "20.00"))
    res = await client.get(f"/api/v1/transactions?event_id={boda['id']}", headers=ctx["headers"])
    assert [t["id"] for t in res.json()["items"]] == [mine["id"]]


# --- Permissions (ESP-03, GLO-05) ------------------------------------------------------------


async def test_evt_permissions_viewer_and_nonmember(client):
    owner = await bootstrap_space(client)
    shared = await client.post("/api/v1/spaces", headers=owner["headers"], json={"name": "Casa"})
    space_id = shared.json()["id"]
    owner_sh = {**owner["headers"], "X-Space-Id": space_id}
    res = await client.post("/api/v1/events", headers=owner_sh, json={"name": "Boda"})
    event_id = res.json()["id"]

    viewer = await add_member(client, owner["headers"], space_id, "viewer", "viewer@example.com")
    assert (await client.get(f"/api/v1/events/{event_id}", headers=viewer)).status_code == 200
    res = await client.post("/api/v1/events", headers=viewer, json={"name": "Viaje"})
    assert res.status_code == 403
    res = await client.patch(f"/api/v1/events/{event_id}", headers=viewer, json={"name": "X"})
    assert res.status_code == 403
    assert (await client.delete(f"/api/v1/events/{event_id}", headers=viewer)).status_code == 403

    stranger = await bootstrap_space(client)
    res = await client.get(
        f"/api/v1/events/{event_id}", headers={**stranger["headers"], "X-Space-Id": space_id}
    )
    assert res.status_code == 404
