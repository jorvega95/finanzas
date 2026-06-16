"""Fase 1 tests: REC-01..REC-05 (caso obligatorio 5) y FX-02."""

from datetime import date
from decimal import Decimal

from freezegun import freeze_time

from app.models.fx import ExchangeRate
from app.services import fx
from tests.conftest import bootstrap_space


def rule_payload(ctx, **overrides):
    base = {
        "type": "expense",
        "amount": "199.00",
        "currency": "MXN",
        "description": "Spotify",
        "category_id": ctx["categories"]["Entretenimiento"]["id"],
        "payment_method_id": ctx["methods"]["Débito"]["id"],
        "frequency": "monthly",
        "start_date": "2026-01-15",
        "month_day": 15,
    }
    base.update(overrides)
    return base


async def generate(client, ctx):
    res = await client.post("/api/v1/recurring-rules/generate", headers=ctx["headers"])
    assert res.status_code == 200
    return res.json()["created"]


@freeze_time("2026-06-10 18:00:00")
async def test_rec02_idempotent_and_rec05_catchup(client):
    """Caso obligatorio 5: correr el job 2 veces ⇒ cero duplicados; downtime
    ⇒ todas las instancias faltantes en orden."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/recurring-rules", headers=ctx["headers"], json=rule_payload(ctx)
    )
    assert res.status_code == 201

    # Catch-up REC-05: Jan 15 .. Jun 10 => 5 instances (15 jun no ha llegado).
    assert await generate(client, ctx) == 5
    # Second run, same day (REC-02): zero new.
    assert await generate(client, ctx) == 0

    res = await client.get("/api/v1/transactions?needs_review=true", headers=ctx["headers"])
    body = res.json()
    assert body["total"] == 5  # REC-03: all born pending review
    dates = sorted(t["date"] for t in body["items"])
    assert dates == [
        "2026-01-15",
        "2026-02-15",
        "2026-03-15",
        "2026-04-15",
        "2026-05-15",
    ]


@freeze_time("2026-03-05 18:00:00")
async def test_rec01_monthly_day31_clamps_to_short_months(client):
    """REC-01: día 31 con ajuste a último día (feb 28 en 2026, no bisiesto)."""
    ctx = await bootstrap_space(client)
    await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json=rule_payload(ctx, start_date="2026-01-31", month_day=31, description="Renta"),
    )
    assert await generate(client, ctx) == 2
    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    dates = sorted(t["date"] for t in res.json()["items"])
    assert dates == ["2026-01-31", "2026-02-28"]


@freeze_time("2026-06-10 18:00:00")
async def test_rec03_discard_creates_tombstone_and_confirm(client):
    ctx = await bootstrap_space(client)
    await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json=rule_payload(ctx, start_date="2026-04-15"),
    )
    assert await generate(client, ctx) == 2  # abr 15, may 15

    res = await client.get("/api/v1/transactions?needs_review=true", headers=ctx["headers"])
    items = res.json()["items"]

    # Discard one instance => tombstone => never regenerated (REC-03).
    res = await client.delete(f"/api/v1/transactions/{items[0]['id']}", headers=ctx["headers"])
    assert res.status_code == 204
    assert await generate(client, ctx) == 0

    # Confirm the other adjusting the amount (variable bill).
    res = await client.post(
        f"/api/v1/transactions/{items[1]['id']}/confirm",
        headers=ctx["headers"],
        json={"amount": "215.50"},
    )
    assert res.status_code == 200
    assert res.json()["needs_review"] is False
    assert res.json()["amount"] == "215.50"


@freeze_time("2026-06-10 18:00:00")
async def test_rec04_edit_affects_only_future_and_autopause(client):
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json=rule_payload(ctx, start_date="2026-04-15"),
    )
    rule = res.json()
    assert await generate(client, ctx) == 2  # abr 15, may 15

    # REC-04: editing the rule does not touch generated instances.
    res = await client.patch(
        f"/api/v1/recurring-rules/{rule['id']}",
        headers=ctx["headers"],
        json={"amount": "249.00"},
    )
    assert res.status_code == 200
    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    assert all(t["amount"] == "199.00" for t in res.json()["items"])

    # REC-04: rule pointing at a deactivated category auto-pauses.
    cat_id = ctx["categories"]["Entretenimiento"]["id"]
    await client.patch(
        f"/api/v1/catalogs/categories/{cat_id}",
        headers=ctx["headers"],
        json={"is_active": False},
    )
    assert await generate(client, ctx) == 0
    res = await client.get("/api/v1/recurring-rules?include_inactive=true", headers=ctx["headers"])
    assert res.json()[0]["is_active"] is False


@freeze_time("2026-06-10 18:00:00")
async def test_rec01_weekly_and_end_date(client):
    ctx = await bootstrap_space(client)
    await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json=rule_payload(
            ctx,
            frequency="weekly",
            start_date="2026-05-20",
            end_date="2026-06-03",
            month_day=None,
        ),
    )
    assert await generate(client, ctx) == 3  # may 20, 27, jun 3
    res = await client.get("/api/v1/transactions", headers=ctx["headers"])
    dates = sorted(t["date"] for t in res.json()["items"])
    assert dates == ["2026-05-20", "2026-05-27", "2026-06-03"]


@freeze_time("2026-06-10 18:00:00")
async def test_rec_income_create_and_confirm(client):
    """Ingreso recurrente: instancia generada nace con needs_review=True (REC-03)
    y al confirmar queda como transacción de tipo income normal."""
    ctx = await bootstrap_space(client)
    income_cat_id = ctx["categories"]["Nómina"]["id"]
    method_id = ctx["methods"]["Débito"]["id"]

    res = await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json={
            "type": "income",
            "amount": "15000.00",
            "currency": "MXN",
            "description": "Nómina quincenal",
            "category_id": income_cat_id,
            "payment_method_id": method_id,
            "frequency": "biweekly",
            "start_date": "2026-05-28",
        },
    )
    assert res.status_code == 201
    assert res.json()["type"] == "income"

    created = await generate(client, ctx)
    assert created == 1  # may 28 (<=jun 10); jun 11 > jun 10 → no generada aún

    res = await client.get("/api/v1/transactions?needs_review=true", headers=ctx["headers"])
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "income"
    assert items[0]["needs_review"] is True

    # Confirmar: needs_review → False, tipo se conserva.
    res = await client.post(
        f"/api/v1/transactions/{items[0]['id']}/confirm", headers=ctx["headers"], json={}
    )
    assert res.status_code == 200
    assert res.json()["needs_review"] is False
    assert res.json()["type"] == "income"


@freeze_time("2026-06-10 18:00:00")
async def test_rec_delete_rule_physical(client):
    """DELETE /recurring-rules/{id}: elimina la regla físicamente; las
    transacciones ya confirmadas quedan intactas con recurring_rule_id=NULL."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json=rule_payload(ctx, start_date="2026-04-15"),
    )
    rule_id = res.json()["id"]
    await generate(client, ctx)  # genera abr 15, may 15

    # Confirmar la primera instancia.
    res = await client.get("/api/v1/transactions?needs_review=true", headers=ctx["headers"])
    txn_id = res.json()["items"][0]["id"]
    await client.post(
        f"/api/v1/transactions/{txn_id}/confirm", headers=ctx["headers"], json={}
    )

    # Eliminar la regla.
    res = await client.delete(f"/api/v1/recurring-rules/{rule_id}", headers=ctx["headers"])
    assert res.status_code == 204

    # La regla ya no existe.
    res = await client.get(
        "/api/v1/recurring-rules?include_inactive=true", headers=ctx["headers"]
    )
    assert not any(r["id"] == rule_id for r in res.json())

    # La transacción confirmada sigue existiendo.
    res = await client.get(f"/api/v1/transactions/{txn_id}", headers=ctx["headers"])
    assert res.status_code == 200
    assert res.json()["recurring_rule_id"] is None  # FK seteada a NULL


async def test_fx02_carry_forward_on_non_business_days(client, db_session, monkeypatch):
    """FX-02: día inhábil ⇒ se persiste la última tasa con fecha de hoy y flag."""

    async def fake_fix(client=None):
        return date(2026, 6, 5), Decimal("18.4321")  # Friday

    monkeypatch.setattr(fx, "fetch_banxico_fix", fake_fix)
    await fx.sync_usd_mxn_rate(db_session, today=date(2026, 6, 7))  # Sunday

    friday = await db_session.get(ExchangeRate, ("USD", "MXN", date(2026, 6, 5)))
    sunday = await db_session.get(ExchangeRate, ("USD", "MXN", date(2026, 6, 7)))
    assert friday is not None and friday.is_carry_forward is False
    assert sunday is not None and sunday.is_carry_forward is True
    assert sunday.rate == Decimal("18.4321")

    # Idempotent re-run (same day) does not duplicate or fail.
    await fx.sync_usd_mxn_rate(db_session, today=date(2026, 6, 7))


async def test_fx_get_rate_inverse_fallback(db_session):
    db_session.add(
        ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 1), rate=Decimal("20.00"))
    )
    await db_session.commit()
    rate = await fx.get_rate(db_session, "MXN", "USD", date(2026, 6, 2))
    assert rate == Decimal("0.05")
