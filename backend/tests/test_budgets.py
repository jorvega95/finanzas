"""Fase 3 tests: PRE-01..PRE-04."""

from freezegun import freeze_time

from tests.conftest import bootstrap_space
from tests.test_dashboard import add_expense


async def make_budget(client, ctx, category="Comida", month="2026-06", amount="1000.00", **kw):
    res = await client.post(
        "/api/v1/budgets",
        headers=ctx["headers"],
        json={
            "category_id": ctx["categories"][category]["id"],
            "month": month,
            "amount": amount,
            **kw,
        },
    )
    return res


@freeze_time("2026-06-20 18:00:00")
async def test_pre01_unique_per_category_month_and_copy(client):
    ctx = await bootstrap_space(client)
    assert (await make_budget(client, ctx)).status_code == 201
    assert (await make_budget(client, ctx)).status_code == 409  # PRE-01 único
    assert (await make_budget(client, ctx, category="Transporte")).status_code == 201

    # Subcategoría no admite presupuesto (PRE-01: categoría raíz).
    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=ctx["headers"],
        json={"name": "Tacos", "kind": "expense", "parent_id": ctx["categories"]["Comida"]["id"]},
    )
    res = await client.post(
        "/api/v1/budgets",
        headers=ctx["headers"],
        json={"category_id": res.json()["id"], "month": "2026-06", "amount": "100.00"},
    )
    assert res.status_code == 422

    # PRE-01: repetir presupuestos en bloque.
    res = await client.post(
        "/api/v1/budgets/copy",
        headers=ctx["headers"],
        json={"from_month": "2026-06", "to_month": "2026-07"},
    )
    assert res.json()["copied"] == 2
    res = await client.get("/api/v1/budgets?month=2026-07", headers=ctx["headers"])
    assert len(res.json()) == 2
    # Re-copiar no duplica.
    res = await client.post(
        "/api/v1/budgets/copy",
        headers=ctx["headers"],
        json={"from_month": "2026-06", "to_month": "2026-07"},
    )
    assert res.json()["copied"] == 0


@freeze_time("2026-06-20 18:00:00")
async def test_pre02_consumption_with_subcategories(client):
    """PRE-02: suma subcategorías, excluye transfers, en moneda base."""
    ctx = await bootstrap_space(client)
    await make_budget(client, ctx, amount="500.00")

    sub = (
        await client.post(
            "/api/v1/catalogs/categories",
            headers=ctx["headers"],
            json={
                "name": "Tacos",
                "kind": "expense",
                "parent_id": ctx["categories"]["Comida"]["id"],
            },
        )
    ).json()
    await add_expense(client, ctx, "100.00")  # Comida
    await add_expense(client, ctx, "60.00", category_id=sub["id"])  # subcategoría
    await add_expense(client, ctx, "999.00", category="Transporte")  # otra categoría
    # Transfer no cuenta (TXN-02/PRE-02).
    await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "transfer",
            "date": "2026-06-02",
            "amount": "500.00",
            "currency": "MXN",
            "payment_method_id": ctx["methods"]["Débito"]["id"],
            "payment_method_to_id": ctx["methods"]["Efectivo"]["id"],
        },
    )

    rows = (await client.get("/api/v1/budgets?month=2026-06", headers=ctx["headers"])).json()
    row = rows[0]
    assert row["category_name"] == "Comida"
    assert row["consumed"] == "160.00"
    assert row["remaining"] == "340.00"  # PRE-04: variación vs presupuesto


@freeze_time("2026-06-20 18:00:00")
async def test_pre03_alerts_once_per_level(client):
    """PRE-03: una alerta al cruzar el umbral y una al 100%, sin spam."""
    ctx = await bootstrap_space(client)
    await make_budget(client, ctx, amount="100.00", alert_threshold=0.8)

    async def check():
        res = await client.post(
            "/api/v1/budgets/check-alerts?month=2026-06", headers=ctx["headers"]
        )
        return res.json()["created"]

    assert await check() == 0  # sin consumo, sin alertas

    await add_expense(client, ctx, "85.00")
    assert await check() == 2  # umbral 80% (in_app + email)
    assert await check() == 0  # idempotente: no spam por transacción

    await add_expense(client, ctx, "20.00")  # 105% del presupuesto
    assert await check() == 2  # nivel 100%
    assert await check() == 0

    # REM-06: el historial conserva los avisos aún no disparados.
    all_reminders = (
        await client.get("/api/v1/notifications/history", headers=ctx["headers"])
    ).json()
    budget_alerts = [
        r for r in all_reminders if r["kind"] == "budget_alert" and r["channel"] == "in_app"
    ]
    assert len(budget_alerts) == 2  # in_app: una por nivel
    assert all("Comida" in r["message"] for r in budget_alerts)
