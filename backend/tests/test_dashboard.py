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
    assert body["totals"]["income"] == "8000.00"
    assert body["totals"]["expenses"] == "150.00"
    assert body["totals"]["net"] == "7850.00"


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
    assert body["totals"]["expenses"] == "1000.00"  # ni 12,000 ni 13,000
    # La cuota hereda la categoría de la compra (MSI-03).
    comida = next(r for r in body["by_category"] if r["category_name"] == "Comida")
    assert comida["total"] == "1000.00"
    # Naturaleza heredada (Comida = variable).
    assert body["by_nature"]["variable"] == "1000.00"


@freeze_time("2026-06-20 18:00:00")
async def test_dsh04_accrued_spending(client):
    """DSH-04: el gasto es devengado (cuándo compraste). La compra TDC cuenta
    en su fecha; el pago del statement (transfer) nunca toca los agregados."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    await charge(client, ctx, card["payment_method_id"], "2026-06-10", "500.00")
    await add_expense(client, ctx, "200.00")  # efectivo: gasto inmediato
    closed = await close_cycles(client, ctx)

    body = await summary(client, ctx)
    # Compra TDC (500) + efectivo (200) cuentan ambos en su fecha de compra.
    assert body["totals"]["expenses"] == "700.00"

    # Pago de tarjeta: es transfer (TXN-02), no altera el gasto devengado.
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
    assert body["totals"]["expenses"] == "700.00"


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
    assert Decimal(body["totals"]["expenses"]) == Decimal("340.00")


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
    assert by_month["2026-06"]["expenses"] == body["totals"]["expenses"] == "250.00"
    assert len(body["trend"]) == 6


async def nature_detail(client, ctx, nature, month="2026-06"):
    res = await client.get(
        f"/api/v1/dashboard/by-nature/{nature}?month={month}", headers=ctx["headers"]
    )
    assert res.status_code == 200, res.text
    return res.json()


@freeze_time("2026-06-20 18:00:00")
async def test_dsh06_detail_matches_pie(client):
    """DSH-06: el drill-down cuadra con el agregado del pie y con sus propias
    categorías; los transfers y las fechas futuras siguen fuera."""
    ctx = await bootstrap_space(client)
    await add_expense(client, ctx, "100.00", category="Comida")  # variable
    await add_expense(client, ctx, "50.00", category="Transporte")  # variable
    await add_expense(client, ctx, "8000.00", category="Vivienda")  # fixed
    await add_expense(client, ctx, "300.00", category="Entretenimiento")  # discretionary
    await add_expense(client, ctx, "999.00", date_str="2026-06-25")  # futura: fuera (TXN-03)
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

    body = await summary(client, ctx)
    for nature, expected in body["by_nature"].items():
        detail = await nature_detail(client, ctx, nature)
        assert detail["nature"] == nature
        assert detail["month"] == "2026-06"
        assert Decimal(detail["total"]) == Decimal(expected)
        assert sum(Decimal(i["amount"]) for i in detail["items"]) == Decimal(expected)
        assert sum(Decimal(c["total"]) for c in detail["by_category"]) == Decimal(expected)

    variable = await nature_detail(client, ctx, "variable")
    assert {i["description"] for i in variable["items"]} == {""}
    assert {i["category_name"] for i in variable["items"]} == {"Comida", "Transporte"}
    assert [i["kind"] for i in variable["items"]] == ["transaction", "transaction"]
    # Ordenado por monto desc.
    assert [i["amount"] for i in variable["items"]] == ["100.00", "50.00"]
    assert variable["items"][0]["payment_method_name"] == "Efectivo"
    assert variable["items"][0]["original_amount"] is None  # ya está en base

    fixed = await nature_detail(client, ctx, "fixed")
    assert Decimal(fixed["total"]) == Decimal("8000.00")
    assert [c["category_name"] for c in fixed["by_category"]] == ["Vivienda"]


@freeze_time("2026-06-20 18:00:00")
async def test_dsh06_override_wins_over_category(client):
    """DSH-06 + CAT-03: el override por transacción manda sobre la categoría."""
    ctx = await bootstrap_space(client)
    await add_expense(client, ctx, "100.00", category="Comida")  # variable
    # Comida es variable, pero esta compra se marca como fija.
    await add_expense(client, ctx, "700.00", category="Comida", expense_nature_override="fixed")

    variable = await nature_detail(client, ctx, "variable")
    fixed = await nature_detail(client, ctx, "fixed")
    assert Decimal(variable["total"]) == Decimal("100.00")
    assert Decimal(fixed["total"]) == Decimal("700.00")
    assert [i["amount"] for i in fixed["items"]] == ["700.00"]


@freeze_time("2026-06-20 18:00:00")
async def test_dsh06_msi_quota_not_parent(client):
    """DSH-06 + MSI-03: el detalle lista la CUOTA (1,000), nunca la madre."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "12000.00", "Laptop")
    res = await client.post(
        "/api/v1/installment-plans",
        headers=ctx["headers"],
        json={"transaction_id": txn["id"], "months": 12},
    )
    assert res.status_code == 201
    await close_cycles(client, ctx)

    detail = await nature_detail(client, ctx, "variable")  # Comida = variable
    assert Decimal(detail["total"]) == Decimal("1000.00")
    assert len(detail["items"]) == 1
    quota = detail["items"][0]
    assert quota["kind"] == "msi_quota"
    assert quota["amount"] == "1000.00"
    assert (quota["installment_number"], quota["installment_total"]) == (1, 12)
    assert quota["description"] == "Laptop"
    assert quota["category_name"] == "Comida"  # heredada de la compra


@freeze_time("2026-06-20 18:00:00")
async def test_dsh06_subcategory_rolls_up_and_fx(client, db_session):
    """DSH-06 + CAT-06/FX-05: el reparto agrupa en la raíz, pero el movimiento
    conserva su subcategoría y su monto original si la moneda ≠ base."""
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

    detail = await nature_detail(client, ctx, "variable")
    by_category = {c["category_name"]: c["total"] for c in detail["by_category"]}
    assert Decimal(by_category["Comida"]) == Decimal("160.00")  # 100 + 60 subcategoría
    assert Decimal(by_category["Transporte"]) == Decimal("180.00")  # 10 USD × 18
    assert "Tacos" in {i["category_name"] for i in detail["items"]}  # el ítem no se colapsa

    usd = next(i for i in detail["items"] if i["currency"] == "USD")
    assert Decimal(usd["amount"]) == Decimal("180.00")  # base (FX-05)
    assert Decimal(usd["original_amount"]) == Decimal("10.00")


@freeze_time("2026-06-20 18:00:00")
async def test_dsh06_requires_membership_and_valid_nature(client):
    """DSH-06 + GLO-05: no-miembro ⇒ 404; naturaleza inexistente ⇒ 422."""
    ctx = await bootstrap_space(client)
    other = await bootstrap_space(client)
    res = await client.get(
        "/api/v1/dashboard/by-nature/fixed?month=2026-06",
        headers={**other["headers"], "X-Space-Id": ctx["space_id"]},
    )
    assert res.status_code == 404

    res = await client.get(
        "/api/v1/dashboard/by-nature/inexistente?month=2026-06", headers=ctx["headers"]
    )
    assert res.status_code == 422
