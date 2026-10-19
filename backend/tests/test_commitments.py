"""Vendor commitments: CXP-01..CXP-08.

Mandatory case 18.
"""

from freezegun import freeze_time

from tests.conftest import bootstrap_space
from tests.test_accounts import add_member, create_card
from tests.test_events import get_summary, make_event, set_event
from tests.test_wallets import get_account, post_txn


async def make_commitment(client, ctx, expected=201, **body):
    payload = {"name": "Salón", "total_amount": "80000.00", **body}
    res = await client.post("/api/v1/commitments", headers=ctx["headers"], json=payload)
    assert res.status_code == expected, res.text
    return res.json()


async def get_commitment(client, ctx, commitment_id):
    res = await client.get(f"/api/v1/commitments/{commitment_id}", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


def abono(ctx, commitment_id, amount, account=None, day="2026-06-20", **extra):
    return {
        "type": "expense",
        "date": day,
        "amount": amount,
        "currency": "MXN",
        "category_id": ctx["expense_categories"]["Entretenimiento"]["id"],
        "account_id": account or ctx["accounts"]["Débito"]["id"],
        "commitment_id": commitment_id,
        "description": "Abono salón",
        **extra,
    }


async def forecast(client, ctx):
    res = await client.get("/api/v1/dashboard/forecast?horizon_months=3", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


# --- Mandatory case 18: CXP-02/03/04/07 -------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_cxp_mandatory_case_18(client):
    ctx = await bootstrap_space(client)
    boda = await make_event(client, ctx)
    salon = await make_commitment(
        client,
        ctx,
        event_id=boda["id"],
        paid_before_tracking="20000.00",
        schedule=[
            {"due_date": "2026-07-20", "amount": "30000.00"},
            {"due_date": "2026-08-20", "amount": "30000.00"},
        ],
    )
    assert salon["pending"] == "60000.00"
    assert salon["status"] == "pending"

    txn = await post_txn(client, ctx, **abono(ctx, salon["id"], "40000.00"))
    assert txn["event_id"] == boda["id"]  # inherited from the commitment
    body = await get_commitment(client, ctx, salon["id"])
    assert body["paid"] == "60000.00"
    assert body["pending"] == "20000.00"
    first, second = body["schedule"]
    assert first["is_covered"] is True and first["uncovered"] == "0.00"
    assert second["is_covered"] is False and second["uncovered"] == "20000.00"

    # CXP-07: only the uncovered 20,000 on its date.
    commitment_events = [
        (e["date"], e["amount"])
        for e in (await forecast(client, ctx))["events"]
        if e["kind"] == "commitment"
    ]
    assert commitment_events == [("2026-08-20", "20000.00")]

    # CXP-03: an abono never leaves the pending below zero.
    res = await client.post(
        "/api/v1/transactions", headers=ctx["headers"], json=abono(ctx, salon["id"], "25000.00")
    )
    assert res.status_code == 422
    assert "edita el total" in res.json()["detail"]

    # CXP-04: paid directly by a third party as a gift.
    cash = ctx["accounts"]["Efectivo"]["id"]
    res = await client.post(
        f"/api/v1/commitments/{salon['id']}/third-party",
        headers=ctx["headers"],
        json={
            "amount": "20000.00",
            "date": "2026-06-20",
            "account_id": cash,
            "category_id": ctx["expense_categories"]["Entretenimiento"]["id"],
            "description": "Tío Juan",
        },
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["commitment"]["status"] == "paid"
    assert out["commitment"]["pending"] == "0.00"
    assert out["income"]["category_id"] == ctx["income_categories"]["Regalos recibidos"]["id"]
    assert (await get_account(client, ctx, cash))["balance"] == "0.00"
    summary = await get_summary(client, ctx, boda["id"])
    # EVT-03: 20,000 paid before the app + 40,000 abono + 20,000 third party.
    assert summary["spent"] == "80000.00"
    assert summary["spent_before_tracking"] == "20000.00"
    assert summary["received"] == "20000.00"
    assert summary["pending_commitments"] == "0.00"
    assert [e for e in (await forecast(client, ctx))["events"] if e["kind"] == "commitment"] == []


# --- CXP-01/02: validation --------------------------------------------------------------------


async def test_cxp01_02_validation(client):
    ctx = await bootstrap_space(client)
    await make_commitment(client, ctx, expected=422, paid_before_tracking="90000.00")
    res = await make_commitment(
        client,
        ctx,
        expected=422,
        paid_before_tracking="20000.00",
        schedule=[{"due_date": "2026-07-01", "amount": "70000.00"}],
    )
    assert "calendario" in res["detail"]
    await make_commitment(
        client, ctx, expected=422, category_id=ctx["income_categories"]["Nómina"]["id"]
    )


# --- CXP-03: abono rules ----------------------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_cxp03_abono_rules(client):
    ctx = await bootstrap_space(client)
    boda = await make_event(client, ctx)
    viaje = await make_event(client, ctx, name="Viaje")
    salon = await make_commitment(client, ctx, total_amount="1000.00", event_id=boda["id"])

    # Only an expense; in the commitment's currency; inside its event.
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            **abono(ctx, salon["id"], "100.00"),
            "type": "income",
            "category_id": ctx["income_categories"]["Otros"]["id"],
        },
    )
    assert res.status_code == 422
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=abono(
            ctx, salon["id"], "10.00", account=ctx["accounts"]["Dólares"]["id"], currency="USD"
        ),
    )
    assert res.status_code == 422
    await post_txn(
        client, ctx, expected=422, **abono(ctx, salon["id"], "100.00", event_id=viaje["id"])
    )

    # Editing an abono excludes itself from the pending check.
    txn = await post_txn(client, ctx, **abono(ctx, salon["id"], "1000.00"))
    res = await client.put(
        f"/api/v1/transactions/{txn['id']}",
        headers=ctx["headers"],
        json=abono(ctx, salon["id"], "900.00"),
    )
    assert res.status_code == 200, res.text
    assert (await get_commitment(client, ctx, salon["id"]))["pending"] == "100.00"
    # Its event can't be moved away from the commitment's.
    await set_event(client, ctx, txn["id"], viaje["id"], expected=422)
    # Unlinking it (full edit without commitment_id) frees the pending again.
    body = abono(ctx, salon["id"], "900.00")
    body.pop("commitment_id")
    await client.put(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"], json=body)
    assert (await get_commitment(client, ctx, salon["id"]))["pending"] == "1000.00"
    # Listing filter.
    res = await client.get(
        f"/api/v1/transactions?commitment_id={salon['id']}", headers=ctx["headers"]
    )
    assert res.json()["total"] == 0


@freeze_time("2026-06-20 18:00:00")
async def test_cxp03_msi_purchase_counts_in_full(client):
    """An abono paid with a card at MSI counts its whole amount: the vendor
    was paid in full (CXP-03)."""
    from tests.test_msi import make_plan

    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    salon = await make_commitment(client, ctx, total_amount="12000.00")
    purchase = await post_txn(
        client, ctx, **abono(ctx, salon["id"], "12000.00", account=card["id"], day="2026-06-10")
    )
    await make_plan(client, ctx, purchase["id"], 12)
    assert (await get_commitment(client, ctx, salon["id"]))["status"] == "paid"


# --- CXP-04: third party ----------------------------------------------------------------------


async def test_cxp04_rejects_credit_account_and_is_atomic(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    salon = await make_commitment(client, ctx, total_amount="1000.00")
    base = {"date": "2026-06-20", "category_id": ctx["expense_categories"]["Otros"]["id"]}
    res = await client.post(
        f"/api/v1/commitments/{salon['id']}/third-party",
        headers=ctx["headers"],
        json={**base, "amount": "100.00", "account_id": card["id"]},
    )
    assert res.status_code == 422
    # Over the pending: nothing is created (not even the gift).
    res = await client.post(
        f"/api/v1/commitments/{salon['id']}/third-party",
        headers=ctx["headers"],
        json={**base, "amount": "1500.00", "account_id": ctx["accounts"]["Efectivo"]["id"]},
    )
    assert res.status_code == 422
    listing = (await client.get("/api/v1/transactions", headers=ctx["headers"])).json()
    assert listing["total"] == 0


# --- CXP-05/06: status, edit, cancel, delete --------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_cxp05_06_lifecycle(client):
    ctx = await bootstrap_space(client)
    salon = await make_commitment(client, ctx, total_amount="1000.00", due_date="2026-06-10")
    assert salon["is_overdue"] is True  # pending past its due date
    await post_txn(client, ctx, **abono(ctx, salon["id"], "600.00"))

    # CXP-06: the total can't go below what was already paid.
    res = await client.patch(
        f"/api/v1/commitments/{salon['id']}",
        headers=ctx["headers"],
        json={"total_amount": "500.00"},
    )
    assert res.status_code == 409
    res = await client.patch(
        f"/api/v1/commitments/{salon['id']}", headers=ctx["headers"], json={"currency": "USD"}
    )
    assert res.status_code == 409
    # Extras: raise the total, then the abono fits.
    res = await client.patch(
        f"/api/v1/commitments/{salon['id']}",
        headers=ctx["headers"],
        json={
            "total_amount": "1200.00",
            "schedule": [{"due_date": "2026-07-01", "amount": "600.00"}],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["pending"] == "600.00"
    assert res.json()["schedule"][0]["covered"] == "600.00"  # FIFO with the 600 abono

    # With abonos it is canceled, never deleted.
    res = await client.delete(f"/api/v1/commitments/{salon['id']}", headers=ctx["headers"])
    assert res.status_code == 409
    res = await client.patch(
        f"/api/v1/commitments/{salon['id']}", headers=ctx["headers"], json={"is_canceled": True}
    )
    assert res.json()["status"] == "canceled"
    assert res.json()["is_overdue"] is False
    # Hidden by default (CXP-05); new abonos rejected.
    assert (await client.get("/api/v1/commitments", headers=ctx["headers"])).json() == []
    closed = (
        await client.get("/api/v1/commitments?include_closed=true", headers=ctx["headers"])
    ).json()
    assert [c["status"] for c in closed] == ["canceled"]
    await post_txn(client, ctx, expected=422, **abono(ctx, salon["id"], "10.00"))
    # The abonos already made are still spending.
    assert (await client.get("/api/v1/transactions", headers=ctx["headers"])).json()["total"] == 1

    # Without abonos it is deleted physically.
    other = await make_commitment(client, ctx, name="Flores", total_amount="300.00")
    res = await client.delete(f"/api/v1/commitments/{other['id']}", headers=ctx["headers"])
    assert res.status_code == 204


@freeze_time("2026-06-20 18:00:00")
async def test_evt03_paid_before_tracking_counts_in_event_spent(client):
    """EVT-03: what was paid to vendors before using the app is part of the
    event's cost (canceled commitments too), under the commitment's category,
    but it is not a dated movement: monthly aggregates don't see it."""
    ctx = await bootstrap_space(client)
    boda = await make_event(client, ctx, budget="100000.00")
    await make_commitment(
        client,
        ctx,
        event_id=boda["id"],
        total_amount="50000.00",
        paid_before_tracking="15000.00",
        category_id=ctx["expense_categories"]["Entretenimiento"]["id"],
    )
    flores = await make_commitment(
        client,
        ctx,
        name="Flores",
        event_id=boda["id"],
        total_amount="8000.00",
        paid_before_tracking="3000.00",
    )
    await client.patch(
        f"/api/v1/commitments/{flores['id']}", headers=ctx["headers"], json={"is_canceled": True}
    )
    await make_commitment(
        client, ctx, name="Otro", total_amount="999.00", paid_before_tracking="999.00"
    )  # no event

    body = await get_summary(client, ctx, boda["id"])
    assert body["spent"] == "18000.00"
    assert body["spent_before_tracking"] == "18000.00"
    assert body["budget_remaining"] == "82000.00"
    assert body["net"] == "18000.00"
    by_category = {row["category_name"]: row["total"] for row in body["by_category"]}
    assert by_category == {"Entretenimiento": "15000.00", "Sin categoría": "3000.00"}
    assert body["pending_commitments"] == "35000.00"  # the canceled one owes nothing

    totals = (
        await client.get("/api/v1/dashboard/summary?month=2026-06", headers=ctx["headers"])
    ).json()["totals"]
    assert totals["expenses"] == "0.00"


async def test_evt01_event_with_commitments_cannot_be_deleted(client):
    ctx = await bootstrap_space(client)
    boda = await make_event(client, ctx)
    await make_commitment(client, ctx, event_id=boda["id"])
    res = await client.delete(f"/api/v1/events/{boda['id']}", headers=ctx["headers"])
    assert res.status_code == 409


# --- CXP-07: undated pending ------------------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_cxp07_dates_and_undated(client):
    ctx = await bootstrap_space(client)
    await make_commitment(client, ctx, name="Banda", total_amount="5000.00")  # no date
    await make_commitment(
        client,
        ctx,
        name="Foto",
        total_amount="3000.00",
        due_date="2026-07-15",
        schedule=[{"due_date": "2026-06-01", "amount": "1000.00"}],  # overdue
    )
    body = await forecast(client, ctx)
    events = [(e["date"], e["amount"]) for e in body["events"] if e["kind"] == "commitment"]
    # Overdue row dated today; the unscheduled 2,000 on due_date.
    assert events == [("2026-06-20", "1000.00"), ("2026-07-15", "2000.00")]
    assert body["undated_commitments"] == [
        {"description": "Banda", "amount": "5000.00", "currency": "MXN"}
    ]
    # DSH-05: dated obligations show up as upcoming commitments.
    upcoming = (
        await client.get("/api/v1/dashboard/summary?month=2026-06", headers=ctx["headers"])
    ).json()["upcoming"]
    assert [(u["kind"], u["date"], u["is_overdue"]) for u in upcoming] == [
        ("commitment", "2026-06-01", True),
        ("commitment", "2026-07-15", False),
    ]


# --- CXP-08: reminders ------------------------------------------------------------------------


async def _reminders(db_session):
    from sqlalchemy import select

    from app.models.reminders import Reminder, ReminderChannel, ReminderKind

    rows = await db_session.execute(
        select(Reminder).where(
            Reminder.kind == ReminderKind.commitment_due,
            Reminder.channel == ReminderChannel.in_app,
        )
    )
    return sorted((r.fire_at.isoformat(), r.status.value) for r in rows.scalars().all())


@freeze_time("2026-06-20 18:00:00")
async def test_cxp08_reminders_scheduled_and_canceled_when_covered(client, db_session):
    ctx = await bootstrap_space(client)
    salon = await make_commitment(
        client,
        ctx,
        total_amount="2000.00",
        schedule=[
            {"due_date": "2026-06-22", "amount": "1000.00"},  # only the 1-day reminder is future
            {"due_date": "2026-07-10", "amount": "1000.00"},
        ],
    )
    assert await _reminders(db_session) == [
        ("2026-06-21", "pending"),
        ("2026-07-07", "pending"),
        ("2026-07-09", "pending"),
    ]
    db_session.expire_all()
    # Covering the first payment cancels its reminder right away (like REM-01b).
    await post_txn(client, ctx, **abono(ctx, salon["id"], "1000.00"))
    db_session.expire_all()
    assert await _reminders(db_session) == [
        ("2026-06-21", "canceled"),
        ("2026-07-07", "pending"),
        ("2026-07-09", "pending"),
    ]


# --- Permissions (ESP-03, GLO-05) -------------------------------------------------------------


async def test_cxp_permissions_viewer_and_nonmember(client):
    owner = await bootstrap_space(client)
    shared = await client.post("/api/v1/spaces", headers=owner["headers"], json={"name": "Casa"})
    space_id = shared.json()["id"]
    owner_sh = {**owner["headers"], "X-Space-Id": space_id}
    res = await client.post(
        "/api/v1/commitments", headers=owner_sh, json={"name": "Salón", "total_amount": "10.00"}
    )
    commitment_id = res.json()["id"]

    viewer = await add_member(client, owner["headers"], space_id, "viewer", "viewer@example.com")
    url = f"/api/v1/commitments/{commitment_id}"
    assert (await client.get(url, headers=viewer)).status_code == 200
    assert (await client.patch(url, headers=viewer, json={"name": "X"})).status_code == 403
    assert (await client.delete(url, headers=viewer)).status_code == 403
    res = await client.post(
        "/api/v1/commitments", headers=viewer, json={"name": "Flores", "total_amount": "10.00"}
    )
    assert res.status_code == 403

    stranger = await bootstrap_space(client)
    res = await client.get(url, headers={**stranger["headers"], "X-Space-Id": space_id})
    assert res.status_code == 404
