"""Card types and non-credit cards: CAT-08, TAR-01..05, PAT-01/02.

Mandatory cases 9 (debit balance + nómina + insufficient funds) and 10
(net worth includes non-credit card balances).
"""

import uuid

from freezegun import freeze_time

from tests.conftest import auth_headers, bootstrap_space
from tests.test_cards import charge, close_cycles, create_card

# --- helpers -----------------------------------------------------------------


async def make_card(client, ctx, card_type_id, **overrides):
    body = {
        "card_type_id": card_type_id,
        "alias": overrides.pop("alias", "Nómina BBVA"),
        "bank": "BBVA",
        "network": "Visa",
        "last4": overrides.pop("last4", "9999"),
        **overrides,
    }
    res = await client.post("/api/v1/cards", headers=ctx["headers"], json=body)
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    return (await client.get(f"/api/v1/cards/{cid}", headers=ctx["headers"])).json()


async def make_debit(client, ctx, initial_balance="1000.00", **overrides):
    return await make_card(
        client,
        ctx,
        ctx["card_type_by_behavior"]["debit"]["id"],
        initial_balance=initial_balance,
        **overrides,
    )


async def spend(client, ctx, method_id, amount, date="2026-06-10", expected=201, category="Comida"):
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": date,
            "amount": amount,
            "currency": "MXN",
            "category_id": ctx["categories"][category]["id"],
            "payment_method_id": method_id,
        },
    )
    assert res.status_code == expected, res.text
    return res.json()


async def earn(client, ctx, method_id, amount, date="2026-06-12", category="Nómina"):
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "income",
            "date": date,
            "amount": amount,
            "currency": "MXN",
            "category_id": ctx["categories"][category]["id"],
            "payment_method_id": method_id,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- CAT-08: card types catalog ----------------------------------------------


async def test_cat08_seed_card_types(client):
    ctx = await bootstrap_space(client)
    types = ctx["card_types"]
    assert set(types) == {"Crédito", "Débito", "Vales de despensa", "Tarjeta de regalo"}
    assert sorted(ct["behavior"] for ct in types.values()) == [
        "credit",
        "debit",
        "prepaid",
        "prepaid",
    ]
    assert all(ct["is_system"] for ct in types.values())


async def test_cat08_card_type_crud_and_reference_guards(client):
    ctx = await bootstrap_space(client)
    # Create a custom prepaid type.
    res = await client.post(
        "/api/v1/catalogs/card-types",
        headers=ctx["headers"],
        json={"name": "Vales Sodexo", "behavior": "prepaid"},
    )
    assert res.status_code == 201, res.text
    new_type = res.json()
    assert new_type["behavior"] == "prepaid"
    assert new_type["is_system"] is False

    # CAT-08: unique name per space (accent/case-insensitive).
    res = await client.post(
        "/api/v1/catalogs/card-types",
        headers=ctx["headers"],
        json={"name": "vales sodexo", "behavior": "prepaid"},
    )
    assert res.status_code == 409

    # A type with cards cannot be deactivated nor deleted (GLO-03).
    await make_card(client, ctx, new_type["id"], initial_balance="500.00", last4="1111")
    res = await client.patch(
        f"/api/v1/catalogs/card-types/{new_type['id']}",
        headers=ctx["headers"],
        json={"is_active": False},
    )
    assert res.status_code == 409
    res = await client.delete(
        f"/api/v1/catalogs/card-types/{new_type['id']}", headers=ctx["headers"]
    )
    assert res.status_code == 409


async def test_esp03_viewer_cannot_mutate_card_types(client, db_session):
    """ESP-03/caso 8: viewer no puede crear tipos de tarjeta."""
    from app.models.spaces import SpaceMember, SpaceRole

    ctx = await bootstrap_space(client)
    viewer = uuid.uuid4()
    viewer_auth = auth_headers(viewer, "viewer@example.com")
    await client.get("/api/v1/me", headers=viewer_auth)
    db_session.add(
        SpaceMember(space_id=uuid.UUID(ctx["space_id"]), user_id=viewer, role=SpaceRole.viewer)
    )
    await db_session.commit()
    viewer_headers = {**viewer_auth, "X-Space-Id": ctx["space_id"]}

    assert (
        await client.get("/api/v1/catalogs/card-types", headers=viewer_headers)
    ).status_code == 200
    res = await client.post(
        "/api/v1/catalogs/card-types",
        headers=viewer_headers,
        json={"name": "Otra", "behavior": "debit"},
    )
    assert res.status_code == 403


# --- TAR-01/02: fields per behavior ------------------------------------------


async def test_tar02_credit_fields_only_for_credit(client):
    ctx = await bootstrap_space(client)
    debit = ctx["card_type_by_behavior"]["debit"]["id"]
    credit = ctx["card_type_by_behavior"]["credit"]["id"]

    # A debit card must not carry credit fields.
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": debit,
            "alias": "X",
            "bank": "B",
            "network": "Visa",
            "last4": "0001",
            "statement_day": 15,
        },
    )
    assert res.status_code == 422

    # TDC-15: a credit card MAY be saved partially (no cut day yet) and
    # completed later; behavior is still credit, with no balance.
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": credit,
            "alias": "Y",
            "bank": "B",
            "network": "Visa",
            "last4": "0002",
            "payment_due_days": 20,
        },
    )
    assert res.status_code == 201, res.text
    partial = (await client.get(f"/api/v1/cards/{res.json()['id']}", headers=ctx["headers"])).json()
    assert partial["behavior"] == "credit"
    assert partial["statement_day"] is None
    assert partial["balance"] is None

    # TAR-05: opening balance may be zero (empty form) or omitted entirely.
    zero = await make_card(client, ctx, debit, alias="Cero", initial_balance="0", last4="0003")
    assert zero["balance"] == "0.00"
    omitted = await make_card(client, ctx, debit, alias="Vacía", last4="0004")
    assert omitted["balance"] == "0.00"

    # Valid debit card: no credit fields, has a balance, linked debit method.
    card = await make_debit(client, ctx)
    assert card["behavior"] == "debit"
    assert card["statement_day"] is None
    assert card["debt"] is None
    assert card["balance"] == "1000.00"
    methods = (await client.get("/api/v1/catalogs/payment-methods", headers=ctx["headers"])).json()
    linked = [m for m in methods if m["card_id"] == card["id"]]
    assert len(linked) == 1 and linked[0]["type"] == "debit"


# --- TAR-04/05: balance, no statement, immediate cash flow -------------------


@freeze_time("2026-06-20 18:00:00")
async def test_tar04_05_debit_balance_no_statement_immediate(client):
    """Caso 9: gasto descuenta saldo y no toca statements; nómina lo sube."""
    ctx = await bootstrap_space(client)
    card = await make_debit(client, ctx, initial_balance="1000.00")
    method = card["payment_method_id"]

    await spend(client, ctx, method, "300.00")
    await earn(client, ctx, method, "500.00")

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["balance"] == "1200.00"  # 1000 − 300 + 500

    # TAR-04: a debit card never materializes statements.
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    assert statements == []
    assert (await client.post("/api/v1/cards/close-cycles", headers=ctx["headers"])).json() == []

    # DSH-02/04: debit spend is immediate in both accrual and cash flow.
    body = (
        await client.get("/api/v1/dashboard/summary?month=2026-06", headers=ctx["headers"])
    ).json()
    assert body["accrual"]["expenses"] == "300.00"
    assert body["cash_flow"]["expenses"] == "300.00"


@freeze_time("2026-06-20 18:00:00")
async def test_tar05_insufficient_funds_and_overdraft(client):
    ctx = await bootstrap_space(client)
    card = await make_debit(client, ctx, initial_balance="100.00")
    method = card["payment_method_id"]

    await spend(client, ctx, method, "100.00")  # exact balance: allowed
    await spend(client, ctx, method, "0.01", expected=422)  # overdraws: rejected

    od = await make_debit(
        client, ctx, initial_balance="100.00", allow_overdraft=True, alias="OD", last4="8888"
    )
    await spend(client, ctx, od["payment_method_id"], "150.00")  # overdraft allowed
    detail = (await client.get(f"/api/v1/cards/{od['id']}", headers=ctx["headers"])).json()
    assert detail["balance"] == "-50.00"


@freeze_time("2026-06-20 18:00:00")
async def test_msi_rejected_on_non_credit_card(client):
    ctx = await bootstrap_space(client)
    card = await make_debit(client, ctx, initial_balance="5000.00")
    txn = await spend(client, ctx, card["payment_method_id"], "1200.00")
    res = await client.post(
        "/api/v1/installment-plans",
        headers=ctx["headers"],
        json={"transaction_id": txn["id"], "months": 6},
    )
    assert res.status_code == 422


# --- TAR-05: editing initial_balance -----------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_tar05_edit_initial_balance(client):
    """TAR-05: editing initial_balance shifts the computed balance by the delta.
    Covers debit, prepaid, zero edge case, and credit rejection."""
    ctx = await bootstrap_space(client)

    # Debit: initial=1000, spend=200, earn=300 → balance=1100.
    card = await make_debit(client, ctx, initial_balance="1000.00")
    method = card["payment_method_id"]
    await spend(client, ctx, method, "200.00")
    await earn(client, ctx, method, "300.00")

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["balance"] == "1100.00"  # 1000 − 200 + 300

    # Edit initial_balance to 2000 → balance = 2000 − 200 + 300 = 2100.
    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"initial_balance": "2000.00"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["balance"] == "2100.00"
    assert res.json()["initial_balance"] == "2000.00"

    # Edit initial_balance to 0 → balance = 0 − 200 + 300 = 100.
    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"initial_balance": "0"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["balance"] == "100.00"
    assert res.json()["initial_balance"] == "0.00"

    # Prepaid (tarjeta de regalo / vales) also supports initial_balance edits.
    prepaid_type_id = ctx["card_type_by_behavior"]["prepaid"]["id"]
    prepaid = await make_card(
        client,
        ctx,
        prepaid_type_id,
        alias="Vales Comida",
        initial_balance="500.00",
        last4="7777",
    )
    res = await client.patch(
        f"/api/v1/cards/{prepaid['id']}",
        headers=ctx["headers"],
        json={"initial_balance": "800.00"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["balance"] == "800.00"

    # Credit card must reject initial_balance (TAR-02 / service guard).
    from tests.test_cards import create_card as create_credit

    credit = await create_credit(client, ctx)
    res = await client.patch(
        f"/api/v1/cards/{credit['id']}",
        headers=ctx["headers"],
        json={"initial_balance": "500.00"},
    )
    assert res.status_code == 422


# --- PAT-01/02: net worth includes non-credit balances -----------------------


@freeze_time("2026-06-20 18:00:00")
async def test_pat01_net_worth_includes_card_balances(client):
    """Caso 10: patrimonio = inversiones + saldos no-crédito − deuda de crédito."""
    ctx = await bootstrap_space(client)

    # Debit balance: 1000 − 200 = 800 (asset).
    debit = await make_debit(client, ctx, initial_balance="1000.00")
    await spend(client, ctx, debit["payment_method_id"], "200.00")

    # Credit debt: a 500 charge that closes (liability).
    credit = await create_card(client, ctx)
    await charge(client, ctx, credit["payment_method_id"], "2026-06-10", "500.00")
    await close_cycles(client, ctx)

    body = (
        await client.post("/api/v1/investments/net-worth/snapshot", headers=ctx["headers"])
    ).json()
    assert body["assets"] == "800.00"
    assert body["liabilities"] == "500.00"
    assert body["net_worth"] == "300.00"
