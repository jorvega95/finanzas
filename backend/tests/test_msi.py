"""Fase 2 tests: MSI-01..MSI-09 vía API (caso obligatorio 4 a nivel statement)."""

from decimal import Decimal

from freezegun import freeze_time

from tests.conftest import bootstrap_space
from tests.test_cards import charge, close_cycles, create_card


async def make_plan(client, ctx, txn_id, months, expected=201):
    res = await client.post(
        "/api/v1/installment-plans",
        headers=ctx["headers"],
        json={"transaction_id": txn_id, "months": months},
    )
    assert res.status_code == expected, res.text
    return res.json()


@freeze_time("2026-06-20 18:00:00")
async def test_msi01_04_plan_creation_and_schedule(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "1000.00", "TV")

    await make_plan(client, ctx, txn["id"], 3)
    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    assert len(plans) == 1
    summary = plans[0]
    assert summary["description"] == "TV"
    assert summary["pending_count"] == 3
    assert summary["remaining_amount"] == "1000.00"

    # MSI-02: 333.33 × 2 + 333.34.
    amounts = [i["amount"] for i in summary["installments"]]
    assert amounts == ["333.33", "333.33", "333.34"]
    # MSI-04: cuota 1 = fecha de compra (10-jun); cuotas 2 y 3 = period_start
    # de su ciclo (16-jun y 16-jul, primer día tras el corte del 15).
    dates = [i["estimated_charge_date"] for i in summary["installments"]]
    assert dates == ["2026-06-10", "2026-06-16", "2026-07-16"]

    # MSI-01: validaciones.
    cash_txn = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-10",
            "amount": "300.00",
            "currency": "MXN",
            "category_id": ctx["categories"]["Comida"]["id"],
            "payment_method_id": ctx["methods"]["Efectivo"]["id"],
        },
    )
    await make_plan(client, ctx, cash_txn.json()["id"], 3, expected=422)  # sin TDC
    await make_plan(client, ctx, txn["id"], 6, expected=409)  # ya tiene plan


@freeze_time("2026-06-20 18:00:00")
async def test_msi03_parent_excluded_statement_charges_installments(client):
    """Caso obligatorio 4 (nivel statement): compra MSI de 12,000 a 12 meses
    ⇒ el statement del mes refleja 1,000, no 12,000, y ningún total suma 13,000."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "12000.00", "Laptop")
    await make_plan(client, ctx, txn["id"], 12)

    closed = await close_cycles(client, ctx)
    st = next(s for s in closed if s["period_end"] == "2026-06-15")
    # Solo la cuota 1 (1000.00), nunca el total ni total+cuota.
    assert st["computed_total"] == "1000.00"

    # TDC-09: comprometido futuro = 11 cuotas pendientes.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "1000.00"
    assert detail["debt"]["committed_msi"] == "11000.00"
    assert detail["debt"]["total_debt"] == "12000.00"


@freeze_time("2026-06-20 18:00:00")
async def test_msi05_lifecycle_pending_charged_paid(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    debito = ctx["methods"]["Débito"]["id"]
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "900.00")
    await make_plan(client, ctx, txn["id"], 3)

    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    statuses = [i["status"] for i in plans[0]["installments"]]
    assert statuses == ["charged", "pending", "pending"]  # MSI-05

    await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "300.00",
            "from_payment_method_id": debito,
            "date": "2026-06-21",
            "statement_id": statement_id,
        },
    )
    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    statuses = [i["status"] for i in plans[0]["installments"]]
    assert statuses == ["paid", "pending", "pending"]
    assert plans[0]["remaining_amount"] == "600.00"  # MSI-06


@freeze_time("2026-06-20 18:00:00")
async def test_msi06_projection_month_by_card(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "600.00")
    await make_plan(client, ctx, txn["id"], 3)

    rows = (await client.get("/api/v1/installment-plans/projection", headers=ctx["headers"])).json()
    # Cuotas: 10-jun, 16-jun, 16-jul → cuotas 1 y 2 caen en junio (mismo mes).
    assert [(r["month"], r["amount"]) for r in rows] == [
        ("2026-06", "400.00"),
        ("2026-07", "200.00"),
    ]
    assert all(r["card_alias"] == "BBVA Azul" for r in rows)


@freeze_time("2026-06-20 18:00:00")
async def test_msi07_settle_early(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "1200.00")
    plan = await make_plan(client, ctx, txn["id"], 12)
    await close_cycles(client, ctx)  # cuota 1 charged

    res = await client.post(
        f"/api/v1/installment-plans/{plan['id']}/settle", headers=ctx["headers"]
    )
    assert res.status_code == 200
    assert res.json()["status"] == "settled_early"

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    statuses = [i["status"] for i in plans[0]["installments"]]
    assert statuses.count("canceled") == 11
    assert statuses.count("charged") == 1

    # El cargo único por las 11 cuotas (1100) vive en el ciclo abierto.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["committed_msi"] == "0.00"
    assert detail["debt"]["current_cycle_spend"] == "1100.00"


@freeze_time("2026-06-20 18:00:00")
async def test_msi08_delete_purchase_rules(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

    # Plan sin cuotas cargadas: borrar la compra borra el plan.
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-16", "600.00")
    await make_plan(client, ctx, txn["id"], 3)
    res = await client.delete(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"])
    assert res.status_code == 204
    assert (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json() == []

    # Plan con cuota cargada: borrar se bloquea (MSI-08).
    txn2 = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "600.00")
    await make_plan(client, ctx, txn2["id"], 3)
    await close_cycles(client, ctx)
    res = await client.delete(f"/api/v1/transactions/{txn2['id']}", headers=ctx["headers"])
    assert res.status_code == 409


@freeze_time("2026-06-20 18:00:00")
async def test_msi09_currency_mismatch_rejected(client, db_session):
    from datetime import date as dt_date

    from app.models.fx import ExchangeRate

    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)  # tarjeta MXN
    db_session.add(
        ExchangeRate(base="USD", quote="MXN", date=dt_date(2026, 6, 1), rate=Decimal("18.00"))
    )
    await db_session.commit()

    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-10",
            "amount": "100.00",
            "currency": "USD",
            "category_id": ctx["categories"]["Comida"]["id"],
            "payment_method_id": card["payment_method_id"],
            "description": "Compra USD",
        },
    )
    assert res.status_code == 201
    await make_plan(client, ctx, res.json()["id"], 3, expected=422)  # MSI-09
