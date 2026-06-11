"""Fase 2 tests: TDC-01..TDC-12 vía API (caso obligatorio 7) y REM-01/02."""

import uuid

from freezegun import freeze_time

from tests.conftest import auth_headers, bootstrap_space

CARD_PAYLOAD = {
    "alias": "BBVA Azul",
    "bank": "BBVA",
    "network": "Visa",
    "last4": "1234",
    "statement_day": 15,
    "payment_due_days": 20,
}


async def create_card(client, ctx, **overrides):
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json={**CARD_PAYLOAD, **overrides}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def charge(client, ctx, method_id, date, amount, description="Compra"):
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": date,
            "amount": amount,
            "currency": "MXN",
            "category_id": ctx["categories"]["Comida"]["id"],
            "payment_method_id": method_id,
            "description": description,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def close_cycles(client, ctx):
    res = await client.post("/api/v1/cards/close-cycles", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def test_tdc01_validation_and_cat07_method(client):
    ctx = await bootstrap_space(client)

    # last4 inválido.
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json={**CARD_PAYLOAD, "last4": "12a4"}
    )
    assert res.status_code == 422
    # Ambos payment_due_days y payment_day => 422 (exactamente uno).
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={**CARD_PAYLOAD, "payment_day": 5},
    )
    assert res.status_code == 422
    # statement_day 31 inválido (TDC-02: 1-28 o 'last').
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json={**CARD_PAYLOAD, "statement_day": 31}
    )
    assert res.status_code == 422

    card = await create_card(client, ctx)
    assert card["payment_method_id"] is not None

    # CAT-07: el método vinculado existe y referencia la tarjeta.
    methods = (await client.get("/api/v1/catalogs/payment-methods", headers=ctx["headers"])).json()
    linked = [m for m in methods if m["credit_card_id"] == card["id"]]
    assert len(linked) == 1
    assert linked[0]["type"] == "credit_card"

    # TDC-13: categoría "Comisiones e intereses" sembrada con la primera tarjeta.
    cats = (await client.get("/api/v1/catalogs/categories", headers=ctx["headers"])).json()
    assert any(c["name"] == "Comisiones e intereses" for c in cats)


@freeze_time("2026-06-20 18:00:00")
async def test_tdc05_charge_assigned_to_cycle_and_tdc07_close(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    # Compra el 10-jun (corte 15-jun): ciclo [16-may, 15-jun], ya vencido hoy (20).
    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    # Compra el 18-jun: ciclo [16-jun, 15-jul], sigue abierto.
    await charge(client, ctx, method_id, "2026-06-18", "200.00")

    closed = await close_cycles(client, ctx)
    assert len(closed) == 1
    st = closed[0]
    assert st["period_end"] == "2026-06-15"
    assert st["computed_total"] == "500.00"
    assert st["due_date"] == "2026-07-05"  # 15-jun + 20 días (TDC-04)
    assert st["status"] == "closed"

    # Idempotente (correr de nuevo no duplica ni re-cierra).
    assert await close_cycles(client, ctx) == []

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    by_status = {s["status"] for s in statements}
    assert "open" in by_status  # ciclo en curso materializado (TDC-11)

    # TDC-09: deuda = saldo al corte (500) + ciclo en curso (200) + MSI (0).
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "500.00"
    assert detail["debt"]["current_cycle_spend"] == "200.00"
    assert detail["debt"]["committed_msi"] == "0.00"
    assert detail["debt"]["total_debt"] == "700.00"


@freeze_time("2026-06-20 18:00:00")
async def test_tdc10_overpayment_credit_applied_next_close(client):
    """Caso obligatorio 7: pago mayor al statement ⇒ saldo a favor aplicado
    al siguiente cierre."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]
    debito = ctx["methods"]["Débito"]["id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    await charge(client, ctx, method_id, "2026-06-18", "300.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]

    # Pago de 800 contra un statement de 500 ⇒ 300 a favor (TDC-10).
    res = await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "800.00",
            "from_payment_method_id": debito,
            "date": "2026-06-21",
            "statement_id": statement_id,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["type"] == "transfer"  # TXN-02/TDC-10

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    paid = next(s for s in statements if s["id"] == statement_id)
    assert paid["status"] == "paid"
    assert paid["paid_amount"] == "800.00"

    # Cierra el siguiente ciclo (15-jul): 300 de cargos − 300 a favor = 0 ⇒ paid.
    with freeze_time("2026-07-16 18:00:00"):
        closed = await close_cycles(client, ctx)
    next_st = next(s for s in closed if s["period_end"] == "2026-07-15")
    assert next_st["applied_credit"] == "300.00"
    assert next_st["computed_total"] == "0.00"
    assert next_st["status"] == "paid"


@freeze_time("2026-06-20 18:00:00")
async def test_rem01_reminders_scheduled_and_canceled_on_payment(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]
    debito = ctx["methods"]["Débito"]["id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]

    # REM-01: due 5-jul ⇒ recordatorios 2-jul y 4-jul (in_app + email).
    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    assert {r["fire_at"] for r in inbox} == {"2026-07-02", "2026-07-04"}
    # REM-03: el mensaje lleva alias y nunca last4.
    assert all("BBVA Azul" in r["message"] for r in inbox)
    assert all("1234" not in r["message"] for r in inbox)

    # REM-02: re-cerrar no duplica recordatorios.
    await close_cycles(client, ctx)
    inbox2 = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    assert len(inbox2) == len(inbox)

    # REM-01: pagar cancela los pendientes.
    await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "500.00",
            "from_payment_method_id": debito,
            "date": "2026-06-21",
            "statement_id": statement_id,
        },
    )
    inbox3 = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    assert all(r["status"] == "canceled" for r in inbox3)


@freeze_time("2026-06-20 18:00:00")
async def test_tdc06_move_charge_between_cycles(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    txn = await charge(client, ctx, method_id, "2026-06-18", "200.00")
    res = await client.post(
        f"/api/v1/transactions/{txn['id']}/move-cycle",
        headers=ctx["headers"],
        json={"direction": "prev"},
    )
    assert res.status_code == 200

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    prev_st = next(s for s in statements if s["period_end"] == "2026-06-15")
    assert res.json()["id"] == txn["id"]

    # El cargo movido cierra en el ciclo anterior.
    closed = await close_cycles(client, ctx)
    closed_prev = next(s for s in closed if s["id"] == prev_st["id"])
    assert closed_prev["computed_total"] == "200.00"


@freeze_time("2026-06-20 18:00:00")
async def test_tdc12_deactivated_card_keeps_closing(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]
    await charge(client, ctx, method_id, "2026-06-10", "100.00")

    res = await client.patch(
        f"/api/v1/cards/{card['id']}", headers=ctx["headers"], json={"is_active": False}
    )
    assert res.status_code == 200

    # CAT-07: el método vinculado queda inactivo ⇒ no acepta cargos nuevos.
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-19",
            "amount": "50.00",
            "currency": "MXN",
            "category_id": ctx["categories"]["Comida"]["id"],
            "payment_method_id": method_id,
        },
    )
    assert res.status_code == 422

    # TDC-12: sus ciclos siguen cerrando.
    closed = await close_cycles(client, ctx)
    assert any(s["computed_total"] == "100.00" for s in closed)


async def test_glo05_cards_cross_space_404(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

    intruder = await bootstrap_space(client, uuid.uuid4())
    evil = {**auth_headers(intruder["user_id"]), "X-Space-Id": ctx["space_id"]}
    res = await client.get(f"/api/v1/cards/{card['id']}", headers=evil)
    assert res.status_code == 404

    own_headers = intruder["headers"]
    res = await client.get(f"/api/v1/cards/{card['id']}", headers=own_headers)
    assert res.status_code == 404
