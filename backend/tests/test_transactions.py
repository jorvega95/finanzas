"""Fase 1 tests: TXN-01..TXN-05, FX-03 (caso obligatorio 6), GLO-05."""

import uuid
from datetime import date
from decimal import Decimal

from freezegun import freeze_time

from app.models.fx import ExchangeRate
from tests.conftest import auth_headers, bootstrap_space


def expense_payload(ctx, **overrides):
    base = {
        "type": "expense",
        "date": "2026-06-01",
        "amount": "150.50",
        "currency": "MXN",
        "category_id": ctx["categories"]["Comida"]["id"],
        "payment_method_id": ctx["methods"]["Efectivo"]["id"],
        "description": "Tacos",
    }
    base.update(overrides)
    return base


async def test_txn01_create_expense_and_required_fields(client):
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions", headers=ctx["headers"], json=expense_payload(ctx)
    )
    assert res.status_code == 201
    body = res.json()
    assert body["amount"] == "150.50"  # GLO-01: money as string
    assert body["fx_rate_to_base"] is None  # same currency as base

    # Missing category/method => 422.
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, category_id=None),
    )
    assert res.status_code == 422
    # amount <= 0 => 422.
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, amount="0"),
    )
    assert res.status_code == 422
    # Category of the wrong kind => 422.
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, category_id=ctx["categories"]["Nómina"]["id"]),
    )
    assert res.status_code == 422


async def test_txn02_transfer_requires_distinct_methods_no_category(client):
    ctx = await bootstrap_space(client)
    efectivo = ctx["methods"]["Efectivo"]["id"]
    debito = ctx["methods"]["Débito"]["id"]

    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "transfer",
            "date": "2026-06-01",
            "amount": "1000.00",
            "currency": "MXN",
            "payment_method_id": debito,
            "payment_method_to_id": efectivo,
        },
    )
    assert res.status_code == 201

    # Same from/to => 422 (TXN-02).
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "transfer",
            "date": "2026-06-01",
            "amount": "100.00",
            "currency": "MXN",
            "payment_method_id": debito,
            "payment_method_to_id": debito,
        },
    )
    assert res.status_code == 422

    # Category on a transfer => 422.
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "transfer",
            "date": "2026-06-01",
            "amount": "100.00",
            "currency": "MXN",
            "payment_method_id": debito,
            "payment_method_to_id": efectivo,
            "category_id": ctx["categories"]["Comida"]["id"],
        },
    )
    assert res.status_code == 422


@freeze_time("2026-06-10 18:00:00")
async def test_txn03_future_date_capped_at_one_year(client):
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, date="2027-06-10"),
    )
    assert res.status_code == 201
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, date="2027-06-11"),
    )
    assert res.status_code == 422


async def test_txn04_unsupported_currency_rejected(client):
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, currency="EUR"),
    )
    assert res.status_code == 422


async def test_fx03_rate_frozen_at_transaction_date(client, db_session):
    """Caso obligatorio 6: un gasto USD del 2026-01-15 usa la tasa de esa
    fecha; editarlo después no cambia la tasa persistida."""
    ctx = await bootstrap_space(client)
    db_session.add_all(
        [
            ExchangeRate(base="USD", quote="MXN", date=date(2026, 1, 14), rate=Decimal("17.50")),
            ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 1), rate=Decimal("19.00")),
        ]
    )
    await db_session.commit()

    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, currency="USD", date="2026-01-15", amount="100.00"),
    )
    assert res.status_code == 201
    txn = res.json()
    # FX-03: closest previous rate (no rate exactly on the 15th).
    assert Decimal(txn["fx_rate_to_base"]) == Decimal("17.50")

    # Editing description must NOT touch the frozen rate (case 6).
    update = expense_payload(
        ctx, currency="USD", date="2026-01-15", amount="100.00", description="Editada"
    )
    res = await client.put(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"], json=update)
    assert res.status_code == 200
    assert Decimal(res.json()["fx_rate_to_base"]) == Decimal("17.50")

    # Changing the date re-resolves the rate for the new date.
    update["date"] = "2026-06-02"
    res = await client.put(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"], json=update)
    assert res.status_code == 200
    assert Decimal(res.json()["fx_rate_to_base"]) == Decimal("19.00")

    # Manual override wins (FX-03).
    update["fx_rate_override"] = "18.123456"
    res = await client.put(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"], json=update)
    assert Decimal(res.json()["fx_rate_to_base"]) == Decimal("18.123456")


async def test_fx03_no_rate_available_rejects(client):
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json=expense_payload(ctx, currency="USD"),
    )
    assert res.status_code == 422


async def test_txn05_update_basic_fields(client):
    """TXN-05: editar descripción, monto y categoría de un gasto normal."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions", headers=ctx["headers"], json=expense_payload(ctx)
    )
    txn_id = res.json()["id"]

    update = expense_payload(
        ctx,
        description="Editada",
        amount="200.00",
        category_id=ctx["categories"]["Transporte"]["id"],
    )
    res = await client.put(f"/api/v1/transactions/{txn_id}", headers=ctx["headers"], json=update)
    assert res.status_code == 200
    body = res.json()
    assert body["description"] == "Editada"
    assert body["amount"] == "200.00"
    assert body["category_id"] == ctx["categories"]["Transporte"]["id"]


async def test_txn05_update_blocked_for_msi(client, db_session):
    """TXN-05 + MSI-08: editar transacción con plan MSI activo debe rechazarse."""
    from app.models.transactions import Transaction

    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions", headers=ctx["headers"], json=expense_payload(ctx)
    )
    txn_id = res.json()["id"]

    # Simulate an MSI plan by setting installment_plan_id directly (SQLite, no FK check).
    txn = await db_session.get(Transaction, uuid.UUID(txn_id))
    txn.installment_plan_id = uuid.uuid4()
    await db_session.commit()

    res = await client.put(
        f"/api/v1/transactions/{txn_id}",
        headers=ctx["headers"],
        json=expense_payload(ctx),
    )
    assert res.status_code == 422
    assert "MSI" in res.json()["detail"]


async def test_txn05_delete_and_glo05_cross_space_404(client):
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/transactions", headers=ctx["headers"], json=expense_payload(ctx)
    )
    txn_id = res.json()["id"]

    # Another user, own space, pointing at victim's space => 404 always.
    intruder = await bootstrap_space(client, uuid.uuid4())
    evil_headers = {**auth_headers(intruder["user_id"]), "X-Space-Id": ctx["space_id"]}
    res = await client.get(f"/api/v1/transactions/{txn_id}", headers=evil_headers)
    assert res.status_code == 404
    res = await client.delete(f"/api/v1/transactions/{txn_id}", headers=evil_headers)
    assert res.status_code == 404

    # Member viewing own txn from their own space but wrong id => 404.
    res = await client.get(f"/api/v1/transactions/{uuid.uuid4()}", headers=ctx["headers"])
    assert res.status_code == 404

    res = await client.delete(f"/api/v1/transactions/{txn_id}", headers=ctx["headers"])
    assert res.status_code == 204
    res = await client.get(f"/api/v1/transactions/{txn_id}", headers=ctx["headers"])
    assert res.status_code == 404


async def test_list_filters_and_pagination(client):
    ctx = await bootstrap_space(client)
    for i, day in enumerate(["2026-06-01", "2026-06-02", "2026-06-03"]):
        await client.post(
            "/api/v1/transactions",
            headers=ctx["headers"],
            json=expense_payload(ctx, date=day, amount=f"{100 + i}.00"),
        )
    await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "income",
            "date": "2026-06-02",
            "amount": "5000.00",
            "currency": "MXN",
            "category_id": ctx["categories"]["Nómina"]["id"],
            "payment_method_id": ctx["methods"]["Débito"]["id"],
            "description": "Quincena",
        },
    )

    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    assert res.json()["total"] == 4
    res = await client.get("/api/v1/transactions?type=income", headers=ctx["headers"])
    assert res.json()["total"] == 1
    res = await client.get(
        "/api/v1/transactions?date_from=2026-06-02&date_to=2026-06-02",
        headers=ctx["headers"],
    )
    assert res.json()["total"] == 2
    res = await client.get("/api/v1/transactions?limit=2", headers=ctx["headers"])
    body = res.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2
