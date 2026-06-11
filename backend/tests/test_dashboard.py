"""Fase 3 tests: DSH-01..DSH-05 (caso obligatorio 4 completo) y FX-05."""

from datetime import date
from decimal import Decimal

from freezegun import freeze_time

from app.models.fx import ExchangeRate
from tests.conftest import bootstrap_space
from tests.test_cards import charge, close_cycles, create_card


async def summary(client, ctx, month="2026-06"):
    res = await client.get(f"/api/v1/dashboard/summary?month={month}", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def add_expense(client, ctx, amount, date_str="2026-06-05", category="Comida", **kw):
    body = {
        "type": "expense",
        "date": date_str,
        "amount": amount,
        "currency": "MXN",
        "category_id": ctx["categories"][category]["id"],
        "payment_method_id": ctx["methods"]["Efectivo"]["id"],
    }
    body.update(kw)
    res = await client.post("/api/v1/transactions", headers=ctx["headers"], json=body)
    assert res.status_code == 201, res.text
    return res.json()


@freeze_time("2026-06-20 18:00:00")
async def test_dsh02_totals_exclude_transfers_and_future(client):
    """DSH-02 + TXN-02/03: transfers nunca suman; fecha futura no cuenta aún."""
    ctx = await bootstrap_space(client)
    await add_expense(client, ctx, "100.00")
    await add_expense(client, ctx, "50.00", category="Transporte")
    # Income.
    await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "income",
            "date": "2026-06-01",
            "amount": "8000.00",
            "currency": "MXN",
            "category_id": ctx["categories"]["Nómina"]["id"],
            "payment_method_id": ctx["methods"]["Débito"]["id"],
        },
    )
    # Transfer (no debe sumar — TXN-02).
    await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "transfer",
            "date": "2026-06-02",
            "amount": "1000.00",
            "currency": "MXN",
            "payment_method_id": ctx["methods"]["Débito"]["id"],
            "payment_method_to_id": ctx["methods"]["Efectivo"]["id"],
        },
    )
    # Futura dentro del mes (25-jun > hoy 20-jun): excluida hasta su fecha.
    await add_expense(client, ctx, "999.00", date_str="2026-06-25")

    body = await summary(client, ctx)
    assert body["accrual"]["income"] == "8000.00"
    assert body["accrual"]["expenses"] == "150.00"
    assert body["accrual"]["net"] == "7850.00"


@freeze_time("2026-06-20 18:00:00")
async def test_dsh02_msi_case4_full_dashboard(client):
    """Caso obligatorio 4: compra MSI de 12,000 a 12 meses ⇒ el gasto del mes
    refleja 1,000, no 12,000, y ningún agregado suma 13,000."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "12000.00", "Laptop")
    res = await client.post(
        "/api/v1/installment-plans",
        headers=ctx["headers"],
        json={"transaction_id": txn["id"], "months": 12},
    )
    assert res.status_code == 201
    await close_cycles(client, ctx)  # cuota 1 charged en corte 15-jun

    body = await summary(client, ctx)
    assert body["accrual"]["expenses"] == "1000.00"  # ni 12,000 ni 13,000
    # La cuota hereda la categoría de la compra (MSI-03).
    comida = next(r for r in body["by_category"] if r["category_name"] == "Comida")
    assert comida["total"] == "1000.00"
    # Naturaleza heredada (Comida = variable).
    assert body["by_nature"]["variable"] == "1000.00"


@freeze_time("2026-06-20 18:00:00")
async def test_dsh04_accrual_vs_cash_flow(client):
    """DSH-04: devengado registra la compra TDC; flujo solo el pago."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    await charge(client, ctx, card["payment_method_id"], "2026-06-10", "500.00")
    await add_expense(client, ctx, "200.00")  # efectivo: cuenta en ambos
    closed = await close_cycles(client, ctx)

    body = await summary(client, ctx)
    assert body["accrual"]["expenses"] == "700.00"
    assert body["cash_flow"]["expenses"] == "200.00"  # aún no se paga la TDC

    # Pago de tarjeta: aparece en flujo, no en devengado (TXN-02).
    await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "500.00",
            "from_payment_method_id": ctx["methods"]["Débito"]["id"],
            "date": "2026-06-20",
            "statement_id": closed[0]["id"],
        },
    )
    body = await summary(client, ctx)
    assert body["accrual"]["expenses"] == "700.00"
    assert body["cash_flow"]["expenses"] == "700.00"


@freeze_time("2026-06-20 18:00:00")
async def test_dsh03_category_rollup_and_fx(client, db_session):
    """DSH-03 + CAT-06: subcategoría suma al padre; FX-05 con tasa congelada."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=ctx["headers"],
        json={"name": "Tacos", "kind": "expense", "parent_id": ctx["categories"]["Comida"]["id"]},
    )
    sub_id = res.json()["id"]
    await add_expense(client, ctx, "100.00")
    await add_expense(client, ctx, "60.00", category_id=sub_id)

    db_session.add(
        ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 1), rate=Decimal("18.00"))
    )
    await db_session.commit()
    await add_expense(client, ctx, "10.00", currency="USD", category="Transporte")

    body = await summary(client, ctx)
    comida = next(r for r in body["by_category"] if r["category_name"] == "Comida")
    assert comida["total"] == "160.00"  # 100 directo + 60 subcategoría
    transporte = next(r for r in body["by_category"] if r["category_name"] == "Transporte")
    assert Decimal(transporte["total"]) == Decimal("180.00")  # 10 USD × 18.00
    assert Decimal(body["accrual"]["expenses"]) == Decimal("340.00")


@freeze_time("2026-06-20 18:00:00")
async def test_dsh05_upcoming_commitments(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    # Statement por vencer.
    await charge(client, ctx, card["payment_method_id"], "2026-06-10", "500.00")
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-12", "300.00", "Cel")
    await client.post(
        "/api/v1/installment-plans",
        headers=ctx["headers"],
        json={"transaction_id": txn["id"], "months": 3},
    )
    await close_cycles(client, ctx)
    # Recurrente próxima.
    await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "amount": "199.00",
            "currency": "MXN",
            "description": "Spotify",
            "category_id": ctx["categories"]["Entretenimiento"]["id"],
            "payment_method_id": ctx["methods"]["Débito"]["id"],
            "frequency": "monthly",
            "start_date": "2026-01-25",
            "month_day": 25,
        },
    )

    body = await summary(client, ctx)
    kinds = {item["kind"] for item in body["upcoming"]}
    assert {"card_due", "msi_quota", "recurring"} <= kinds
    dates = [item["date"] for item in body["upcoming"]]
    assert dates == sorted(dates)  # ordenados por fecha (DSH-05)
    spotify = next(i for i in body["upcoming"] if i["kind"] == "recurring")
    assert spotify["date"] == "2026-06-25"


@freeze_time("2026-06-20 18:00:00")
async def test_dsh03_trend_consistency(client):
    """DSH-03: la tendencia usa los mismos predicados que el resumen."""
    ctx = await bootstrap_space(client)
    await add_expense(client, ctx, "100.00", date_str="2026-05-10")
    await add_expense(client, ctx, "250.00", date_str="2026-06-05")

    body = await summary(client, ctx)
    by_month = {p["month"]: p for p in body["trend"]}
    assert by_month["2026-05"]["expenses"] == "100.00"
    assert by_month["2026-06"]["expenses"] == body["accrual"]["expenses"] == "250.00"
    assert len(body["trend"]) == 6
