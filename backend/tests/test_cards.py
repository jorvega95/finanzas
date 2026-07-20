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


def credit_payload(ctx, **overrides):
    """CARD_PAYLOAD bound to the seeded 'credit' card type (CAT-08)."""
    return {
        **CARD_PAYLOAD,
        "card_type_id": ctx["card_type_by_behavior"]["credit"]["id"],
        **overrides,
    }


async def create_card(client, ctx, **overrides):
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json=credit_payload(ctx, **overrides)
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


async def refund(client, ctx, method_id, date, amount, description="Devolución"):
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "income",
            "date": date,
            "amount": amount,
            "currency": "MXN",
            "category_id": ctx["categories"]["Nómina"]["id"],
            "payment_method_id": method_id,
            "description": description,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_tdc01_validation_and_cat07_method(client):
    ctx = await bootstrap_space(client)

    # last4 inválido.
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json=credit_payload(ctx, last4="12a4")
    )
    assert res.status_code == 422
    # Ambos payment_due_days y payment_day => 422 (exactamente uno).
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json=credit_payload(ctx, payment_day=5)
    )
    assert res.status_code == 422
    # statement_day 31 inválido (TDC-02: 1-28 o 'last').
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json=credit_payload(ctx, statement_day=31)
    )
    assert res.status_code == 422

    card = await create_card(client, ctx)
    assert card["payment_method_id"] is not None

    # CAT-07: el método vinculado existe y referencia la tarjeta.
    methods = (await client.get("/api/v1/catalogs/payment-methods", headers=ctx["headers"])).json()
    linked = [m for m in methods if m["card_id"] == card["id"]]
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
    # REM-06: aún no se disparan (hoy 20-jun), así que se consultan en el historial.
    async def history():
        res = await client.get("/api/v1/notifications/history", headers=ctx["headers"])
        assert res.status_code == 200, res.text
        return res.json()

    scheduled = await history()
    assert {r["fire_at"] for r in scheduled} == {"2026-07-02", "2026-07-04"}
    # REM-03: el mensaje lleva alias y nunca last4.
    assert all("BBVA Azul" in r["message"] for r in scheduled)
    assert all("1234" not in r["message"] for r in scheduled)

    # REM-02: re-cerrar no duplica recordatorios.
    await close_cycles(client, ctx)
    assert len(await history()) == len(scheduled)

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
    assert all(r["status"] == "canceled" for r in await history())


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


@freeze_time("2026-06-20 18:00:00")
async def test_tdc12_reactivate_card_restores_method(client):
    """TDC-12 + CAT-07: reactivar (is_active=true) restaura la tarjeta y su
    método vinculado, que vuelve a aceptar cargos."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    res = await client.patch(
        f"/api/v1/cards/{card['id']}", headers=ctx["headers"], json={"is_active": False}
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    res = await client.patch(
        f"/api/v1/cards/{card['id']}", headers=ctx["headers"], json={"is_active": True}
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is True

    # CAT-07: el método vinculado vuelve a estar activo y acepta cargos.
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
    assert res.status_code == 201, res.text


async def test_list_cards_include_inactive(client):
    """TDC-12: las tarjetas desactivadas se ocultan por defecto y solo aparecen
    con include_inactive=true (para poder reactivarlas desde la UI)."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

    res = await client.patch(
        f"/api/v1/cards/{card['id']}", headers=ctx["headers"], json={"is_active": False}
    )
    assert res.status_code == 200

    res = await client.get("/api/v1/cards", headers=ctx["headers"])
    assert res.status_code == 200
    assert all(c["id"] != card["id"] for c in res.json())

    res = await client.get("/api/v1/cards?include_inactive=true", headers=ctx["headers"])
    assert res.status_code == 200
    assert any(c["id"] == card["id"] for c in res.json())


# --- TAR-07: orden de tarjetas por usuario ------------------------------------


async def create_card_for(client, headers, alias):
    """Create a credit card in whatever space `headers` points to."""
    types = (await client.get("/api/v1/catalogs/card-types", headers=headers)).json()
    credit = next(t for t in types if t["behavior"] == "credit")
    res = await client.post(
        "/api/v1/cards",
        headers=headers,
        json={**CARD_PAYLOAD, "alias": alias, "card_type_id": credit["id"]},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def put_layout(client, headers, card_ids, expected=204):
    res = await client.put("/api/v1/cards/layout", headers=headers, json={"card_ids": card_ids})
    assert res.status_code == expected, res.text


async def card_order(client, headers):
    res = await client.get("/api/v1/cards", headers=headers)
    assert res.status_code == 200
    return [c["id"] for c in res.json()]


async def add_member(client, owner_headers, space_id, role, email):
    """Invite + claim a new user into the space with the given role."""
    friend = auth_headers(uuid.uuid4(), email)
    await client.get("/api/v1/me", headers=friend)
    inv = await client.post(
        f"/api/v1/spaces/{space_id}/invites",
        headers=owner_headers,
        json={"email": email, "role": role},
    )
    assert inv.status_code == 201, inv.text
    claim = await client.post(
        "/api/v1/invites/claim", headers=friend, json={"token": inv.json()["token"]}
    )
    assert claim.status_code == 200, claim.text
    return {**friend, "X-Space-Id": space_id}


async def test_tar07_layout_reorders_list(client):
    ctx = await bootstrap_space(client)
    a = await create_card_for(client, ctx["headers"], "Alfa")
    b = await create_card_for(client, ctx["headers"], "Beta")
    c = await create_card_for(client, ctx["headers"], "Gama")

    # Línea base alfabética.
    assert await card_order(client, ctx["headers"]) == [a["id"], b["id"], c["id"]]

    await put_layout(client, ctx["headers"], [c["id"], a["id"], b["id"]])
    assert await card_order(client, ctx["headers"]) == [c["id"], a["id"], b["id"]]


async def test_tar07_new_card_appended_at_end(client):
    ctx = await bootstrap_space(client)
    a = await create_card_for(client, ctx["headers"], "Alfa")
    b = await create_card_for(client, ctx["headers"], "Beta")
    await put_layout(client, ctx["headers"], [b["id"], a["id"]])

    # Una tarjeta nueva no está en el layout ⇒ va al final (orden por alias).
    c = await create_card_for(client, ctx["headers"], "Gama")
    assert await card_order(client, ctx["headers"]) == [b["id"], a["id"], c["id"]]


async def test_tar07_unknown_ids_ignored(client):
    ctx = await bootstrap_space(client)
    a = await create_card_for(client, ctx["headers"], "Alfa")
    b = await create_card_for(client, ctx["headers"], "Beta")

    # Un id ajeno al espacio se ignora sin romper.
    await put_layout(client, ctx["headers"], [b["id"], str(uuid.uuid4()), a["id"]])
    assert await card_order(client, ctx["headers"]) == [b["id"], a["id"]]


async def test_tar07_layout_is_per_user(client):
    owner = await bootstrap_space(client)
    shared = await client.post("/api/v1/spaces", headers=owner["headers"], json={"name": "Familia"})
    space_id = shared.json()["id"]
    owner_sh = {**owner["headers"], "X-Space-Id": space_id}

    a = await create_card_for(client, owner_sh, "Alfa")
    b = await create_card_for(client, owner_sh, "Beta")
    c = await create_card_for(client, owner_sh, "Gama")

    friend = await add_member(client, owner["headers"], space_id, "editor", "amigo@example.com")

    await put_layout(client, owner_sh, [c["id"], b["id"], a["id"]])
    await put_layout(client, friend, [b["id"], a["id"], c["id"]])

    # Cada usuario ve su propio orden; el del owner no afecta al del amigo.
    assert await card_order(client, owner_sh) == [c["id"], b["id"], a["id"]]
    assert await card_order(client, friend) == [b["id"], a["id"], c["id"]]


async def test_tar07_viewer_can_reorder_and_nonmember_404(client):
    owner = await bootstrap_space(client)
    shared = await client.post("/api/v1/spaces", headers=owner["headers"], json={"name": "Casa"})
    space_id = shared.json()["id"]
    owner_sh = {**owner["headers"], "X-Space-Id": space_id}

    a = await create_card_for(client, owner_sh, "Uno")
    b = await create_card_for(client, owner_sh, "Dos")

    # Un viewer SÍ puede reordenar su propia vista (no es mutación de dominio).
    viewer = await add_member(client, owner["headers"], space_id, "viewer", "viewer@example.com")
    await put_layout(client, viewer, [b["id"], a["id"]])
    assert await card_order(client, viewer) == [b["id"], a["id"]]

    # Un no-miembro recibe 404 (GLO-05), nunca 403.
    intruder = auth_headers(uuid.uuid4(), "evil@example.com")
    await client.get("/api/v1/me", headers=intruder)
    res = await client.put(
        "/api/v1/cards/layout",
        headers={**intruder, "X-Space-Id": space_id},
        json={"card_ids": []},
    )
    assert res.status_code == 404


# --- TDC-14: opening debt --------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_tdc14_opening_balance(client):
    """TDC-14: la deuda del corte anterior entra como statement cerrado y es
    pagable (TDC-10), reflejándose en TDC-09."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, opening_balance="1500.00")

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "1500.00"
    assert detail["debt"]["total_debt"] == "1500.00"
    # TDC-14/Pieza 2: próximo pago = monto + fecha (corte 15-jun + 20 días = 5-jul).
    assert detail["next_payment"]["amount"] == "1500.00"
    assert detail["next_payment"]["due_date"] == "2026-07-05"

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    opening = [s for s in statements if s["computed_total"] == "1500.00"]
    assert len(opening) == 1 and opening[0]["status"] == "closed"

    # TDC-10: se puede pagar.
    debito = ctx["methods"]["Débito"]["id"]
    res = await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "1500.00",
            "from_payment_method_id": debito,
            "date": "2026-06-20",
            "statement_id": opening[0]["id"],
        },
    )
    assert res.status_code == 201, res.text
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "0.00"
    assert detail["next_payment"] is None  # ya no hay nada pendiente


@freeze_time("2026-06-20 18:00:00")
async def test_tdc14_opening_balance_via_edit(client):
    """TDC-14: el saldo pendiente del corte anterior se puede añadir por edición
    a una tarjeta ya existente."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)  # sin deuda inicial

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "0.00"
    assert detail["next_payment"] is None

    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"opening_balance": "2300.00"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["debt"]["statement_balance"] == "2300.00"
    assert body["next_payment"]["amount"] == "2300.00"
    assert body["next_payment"]["due_date"] == "2026-07-05"

    # Idempotente: re-editar reemplaza el monto (no duplica el statement).
    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"opening_balance": "2000.00"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["debt"]["statement_balance"] == "2000.00"
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    assert len([s for s in statements if s["status"] == "closed"]) == 1


@freeze_time("2026-06-20 18:00:00")
async def test_tdc14_opening_balance_edit_collision(client):
    """No se sobrepone un saldo manual sobre un corte que ya tiene cargos."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    # Cargo del 10-jun cae en el corte 15-jun (= el corte anterior a hoy 20-jun).
    await charge(client, ctx, card["payment_method_id"], "2026-06-10", "400.00")

    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"opening_balance": "1000.00"},
    )
    assert res.status_code == 409, res.text


async def test_tdc14_opening_balance_requires_config(client):
    ctx = await bootstrap_space(client)
    credit = ctx["card_type_by_behavior"]["credit"]["id"]
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": credit,
            "alias": "Sin config",
            "bank": "B",
            "network": "Visa",
            "last4": "0009",
            "opening_balance": "1000.00",  # sin día de corte ni términos
        },
    )
    assert res.status_code == 422


# --- TDC-15: partial capture + full edit ----------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_tdc15_partial_create_then_complete_by_edit(client):
    ctx = await bootstrap_space(client)
    credit = ctx["card_type_by_behavior"]["credit"]["id"]
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": credit,
            "alias": "Parcial",
            "bank": "B",
            "network": "Visa",
            "last4": "0010",
        },
    )
    assert res.status_code == 201, res.text
    card = res.json()
    method = card["payment_method_id"]

    # TDC-15: sin día de corte, un cargo no se asigna a ningún ciclo.
    await charge(client, ctx, method, "2026-06-18", "500.00")
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    assert statements == []

    # Completar la configuración por edición.
    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"statement_day": 15, "payment_due_days": 20},
    )
    assert res.status_code == 200, res.text
    assert res.json()["statement_day"] == 15

    # Ahora un nuevo cargo sí entra al ciclo en curso.
    await charge(client, ctx, method, "2026-06-19", "200.00")
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "200.00"


async def test_tdc15_edit_fields_and_method_rename(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={
            "alias": "BBVA Oro",
            "bank": "BBVA Bancomer",
            "last4": "4321",
            "credit_limit": "50000.00",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["alias"] == "BBVA Oro"
    assert body["bank"] == "BBVA Bancomer"
    assert body["last4"] == "4321"
    assert body["credit_limit"] == "50000.00"

    # CAT-07: el método vinculado se renombra con el alias.
    methods = (await client.get("/api/v1/catalogs/payment-methods", headers=ctx["headers"])).json()
    linked = [m for m in methods if m["card_id"] == card["id"]]
    assert linked[0]["name"] == "BBVA Oro"


async def test_tdc15_edit_revalidates(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    # statement_day 31 inválido (TDC-02).
    res = await client.patch(
        f"/api/v1/cards/{card['id']}", headers=ctx["headers"], json={"statement_day": 31}
    )
    assert res.status_code == 422
    # last4 no numérico.
    res = await client.patch(
        f"/api/v1/cards/{card['id']}", headers=ctx["headers"], json={"last4": "12a4"}
    )
    assert res.status_code == 422


# --- TDC-06: cargo tardío sobre corte ya cerrado ----------------------------------


@freeze_time("2026-06-22 18:00:00")
async def test_tdc06_late_charge_recomputes_closed_statement(client):
    """TDC-06: agregar un gasto con fecha anterior al último corte (corte=15,
    hoy=22) actualiza el computed_total del statement ya cerrado inmediatamente.
    Antes del fix, el total quedaba stale y la deuda se mostraba incorrecta."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    # Cargo del 10-jun → ciclo [16-may, 15-jun] → se cerrará al close_cycles.
    await charge(client, ctx, method_id, "2026-06-10", "300.00")
    closed = await close_cycles(client, ctx)
    assert len(closed) == 1
    assert closed[0]["computed_total"] == "300.00"

    # Ahora es 22-jun; se agrega un cargo olvidado del 8-jun (mismo ciclo cerrado).
    await charge(client, ctx, method_id, "2026-06-08", "200.00")

    # El statement cerrado debe reflejar 500 sin requerir otro close_cycles.
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    closed_st = next(s for s in statements if s["id"] == closed[0]["id"])
    assert closed_st["computed_total"] == "500.00", (
        f"computed_total no se actualizó tras cargo tardío: {closed_st['computed_total']}"
    )

    # La deuda de la tarjeta también debe reflejar el nuevo total.
    card_data = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert card_data["debt"]["statement_balance"] == "500.00"


# --- TDC-16: reembolso posterior al corte abona al statement pendiente -----------


@freeze_time("2026-06-20 18:00:00")
async def test_tdc16_refund_after_cutoff_reduces_pending_statement(client):
    """Caso obligatorio 12 (parte 1): reembolso entre period_end y due_date de
    un statement closed ⇒ se resta de ese computed_total, no del ciclo abierto."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]
    assert closed[0]["due_date"] == "2026-07-05"

    # Devolución el 18-jun: después del corte (15-jun), antes del due_date (5-jul).
    txn = await refund(client, ctx, method_id, "2026-06-18", "200.00")
    assert txn["statement_id"] == statement_id

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    st = next(s for s in statements if s["id"] == statement_id)
    assert st["computed_total"] == "300.00"
    assert st["status"] == "closed"

    card_data = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert card_data["debt"]["statement_balance"] == "300.00"


@freeze_time("2026-06-20 18:00:00")
async def test_tdc16_refund_without_pending_statement_falls_back_to_tdc05(client):
    """Caso obligatorio 12 (parte 2): sin ningún statement closed/partially_paid
    pendiente, el reembolso cae en la asignación normal de TDC-05 (ciclo abierto)."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    # Tarjeta recién creada: no hay ningún statement closed todavía.
    txn = await refund(client, ctx, method_id, "2026-06-18", "200.00")

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    st = next(s for s in statements if s["id"] == txn["statement_id"])
    assert st["status"] == "open"
    assert st["period_end"] == "2026-07-15"  # primer corte >= 18-jun (TDC-05)


@freeze_time("2026-06-20 18:00:00")
async def test_tdc16_refund_after_due_date_not_retroactive(client):
    """Caso obligatorio 12 (parte 3): un reembolso posterior al due_date del
    statement pendiente NO lo abona retroactivamente; sigue TDC-05 normal."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]
    assert closed[0]["due_date"] == "2026-07-05"

    with freeze_time("2026-07-10 18:00:00"):
        # 8-jul es posterior al due_date (5-jul) del statement pendiente.
        txn = await refund(client, ctx, method_id, "2026-07-08", "200.00")

    assert txn["statement_id"] != statement_id

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    st = next(s for s in statements if s["id"] == statement_id)
    assert st["computed_total"] == "500.00"  # sin cambios


@freeze_time("2026-06-20 18:00:00")
async def test_pend01_late_refund_does_not_wipe_manual_opening_balance(client):
    """PEND-01 (regresión): un opening_balance manual (TDC-14) se conservaba
    solo mientras el statement no tuviera transacciones itemizadas. Un
    reembolso que TDC-16 le asigna después (misma ventana period_end/due_date)
    NO debe descartar los 1500 capturados a mano; debe restarse de ellos."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, opening_balance="1500.00")
    method_id = card["payment_method_id"]

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    opening = next(s for s in statements if s["computed_total"] == "1500.00")
    assert opening["due_date"] == "2026-07-05"

    # Reembolso el 25-jun: después del corte (15-jun), antes del due_date (5-jul)
    # ⇒ TDC-16 lo asigna a este mismo statement de opening balance.
    txn = await refund(client, ctx, method_id, "2026-06-25", "200.00")
    assert txn["statement_id"] == opening["id"]

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    updated = next(s for s in statements if s["id"] == opening["id"])
    assert updated["computed_total"] == "1300.00", (
        f"opening_balance descartado tras el reembolso: {updated['computed_total']}"
    )

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "1300.00"


@freeze_time("2026-06-20 18:00:00")
async def test_pend01_late_charge_adds_to_manual_opening_balance(client):
    """PEND-01 (regresión): mismo caso que arriba pero con un cargo tardío
    (TDC-06) en vez de un reembolso — debe sumarse a los 1500, no reemplazarlos."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, opening_balance="1500.00")
    method_id = card["payment_method_id"]

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    opening = next(s for s in statements if s["computed_total"] == "1500.00")

    # Cargo olvidado del mismo corte anterior (10-jun, dentro del ciclo cerrado).
    await charge(client, ctx, method_id, "2026-06-10", "300.00")

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    updated = next(s for s in statements if s["id"] == opening["id"])
    assert updated["computed_total"] == "1800.00", (
        f"opening_balance descartado tras el cargo tardío: {updated['computed_total']}"
    )


@freeze_time("2026-06-20 18:00:00")
async def test_tdc16_refund_edit_reassigns(client):
    """Editar la fecha de un reembolso reevalúa TDC-16: si la nueva fecha cae en
    la ventana de un statement pendiente, se reasigna y ambos totales se recalculan."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]

    # Fecha capturada con error (9-jul, posterior al due_date 5-jul) ⇒ cae en TDC-05
    # normal, en el ciclo abierto, no en el statement pendiente.
    txn = await refund(client, ctx, method_id, "2026-07-09", "200.00")
    assert txn["statement_id"] != statement_id

    # Se corrige la fecha a 18-jun (dentro de la ventana del statement pendiente).
    res = await client.put(
        f"/api/v1/transactions/{txn['id']}",
        headers=ctx["headers"],
        json={
            "type": "income",
            "date": "2026-06-18",
            "amount": "200.00",
            "currency": "MXN",
            "category_id": ctx["categories"]["Nómina"]["id"],
            "payment_method_id": method_id,
            "description": "Devolución",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["statement_id"] == statement_id

    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    st = next(s for s in statements if s["id"] == statement_id)
    assert st["computed_total"] == "300.00"
