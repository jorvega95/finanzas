"""Fase 8 tests: pronóstico de flujo a futuro (PRO-01..06).

Caso obligatorio 11: nómina día 15, TDC con due_date día 17; si el ingreso no
cubre el pago hay sobregiro con el faltante exacto. MSI a futuro empuja la deuda
al mes correcto. El pronóstico es read-only (no materializa statements).
"""

from datetime import date
from decimal import Decimal

from freezegun import freeze_time
from sqlalchemy import func, select

from app.models.cards import CardStatement
from app.models.fx import ExchangeRate
from tests.conftest import bootstrap_space
from tests.test_cards import charge, close_cycles, create_card


async def forecast(client, ctx, horizon_months=6, cash_adjustment="0"):
    res = await client.get(
        f"/api/v1/dashboard/forecast?horizon_months={horizon_months}"
        f"&cash_adjustment={cash_adjustment}",
        headers=ctx["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


async def add_income(client, ctx, amount, date_str, currency="MXN", method="Débito"):
    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "income",
            "date": date_str,
            "amount": amount,
            "currency": currency,
            "category_id": ctx["categories"]["Nómina"]["id"],
            "payment_method_id": ctx["methods"][method]["id"],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def add_payroll_rule(client, ctx, amount, day=15, start="2026-01-15"):
    res = await client.post(
        "/api/v1/recurring-rules",
        headers=ctx["headers"],
        json={
            "type": "income",
            "amount": amount,
            "currency": "MXN",
            "description": "Nómina",
            "category_id": ctx["categories"]["Nómina"]["id"],
            "payment_method_id": ctx["methods"]["Débito"]["id"],
            "frequency": "monthly",
            "start_date": start,
            "month_day": day,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


@freeze_time("2026-06-20 18:00:00")
async def test_pro05_overdraft_user_scenario(client):
    """PRO-05 (caso 11): nómina día 15 = 5,000 no cubre el pago de TDC de 8,000
    con due_date día 17 ⇒ sobregiro de 3,000 el 2026-07-17."""
    ctx = await bootstrap_space(client)
    # TDC: corte día 15, pago a +2 días ⇒ due_date día 17.
    card = await create_card(client, ctx, statement_day=15, payment_due_days=2)
    await add_payroll_rule(client, ctx, "5000.00")
    # Cargo el 20-jun ⇒ ciclo que cierra 15-jul, due 17-jul.
    await charge(client, ctx, card["payment_method_id"], "2026-06-20", "8000.00")

    body = await forecast(client, ctx, cash_adjustment="0")

    assert body["first_overdraft_date"] == "2026-07-17"
    due = next(e for e in body["events"] if e["kind"] == "card_due" and e["date"] == "2026-07-17")
    assert due["amount"] == "8000.00"
    assert due["covered"] is False
    assert due["shortfall"] == "3000.00"  # 5,000 nómina − 8,000 pago
    assert Decimal(body["total_shortfall"]) >= Decimal("3000.00")


@freeze_time("2026-06-20 18:00:00")
async def test_pro05_sufficient_no_overdraft(client):
    """PRO-02/05: con caja inicial suficiente el mismo pago queda cubierto."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, statement_day=15, payment_due_days=2)
    await add_payroll_rule(client, ctx, "5000.00")
    await charge(client, ctx, card["payment_method_id"], "2026-06-20", "8000.00")

    # 5,000 caja inicial + 5,000 nómina (15-jul) = 10,000 ≥ 8,000.
    body = await forecast(client, ctx, cash_adjustment="5000.00")

    assert body["first_overdraft_date"] is None
    assert body["total_shortfall"] == "0.00"
    due = next(e for e in body["events"] if e["kind"] == "card_due" and e["date"] == "2026-07-17")
    assert due["covered"] is True
    assert due["shortfall"] == "0.00"


@freeze_time("2026-06-20 18:00:00")
async def test_pro03_msi_future_installments_push_debt(client):
    """PRO-03/MSI-04: las cuotas MSI futuras alimentan los statements proyectados.
    Compra 6,000/6 ⇒ 6 cuotas de 1,000 repartidas en cortes futuros."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, statement_day=15, payment_due_days=2)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "6000.00", "Laptop")
    res = await client.post(
        "/api/v1/installment-plans",
        headers=ctx["headers"],
        json={"transaction_id": txn["id"], "months": 6},
    )
    assert res.status_code == 201, res.text

    body = await forecast(client, ctx, horizon_months=6, cash_adjustment="0")

    card_dues = [e for e in body["events"] if e["kind"] == "card_due"]
    total_card = sum(Decimal(e["amount"]) for e in card_dues)
    # La cuota 1 (corte 15-jun, ya pasado) nace `paid` al registrar la compra,
    # así que el futuro real son las cuotas 2..6 = 5,000.
    assert total_card == Decimal("5000.00")
    # Cuota 2 (cargada en el statement abierto del 15-jul) ⇒ 1,000 el 17-jul.
    first = next(e for e in card_dues if e["date"] == "2026-07-17")
    assert first["amount"] == "1000.00"
    assert body["first_overdraft_date"] == "2026-07-17"  # sin ingresos


@freeze_time("2026-06-20 18:00:00")
async def test_pro03_non_credit_recurring_is_immediate(client):
    """PRO-03/TAR-04: un domiciliado sobre débito sale como flujo inmediato en
    su fecha, no como pago de statement."""
    ctx = await bootstrap_space(client)
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

    body = await forecast(client, ctx, horizon_months=2, cash_adjustment="0")

    spotify = [e for e in body["events"] if e["description"] == "Spotify"]
    assert spotify, body["events"]
    assert all(e["direction"] == "out" and e["kind"] != "card_due" for e in spotify)
    assert spotify[0]["date"] == "2026-06-25"


@freeze_time("2026-06-20 18:00:00")
async def test_pro06_multicurrency_with_rate(client, db_session):
    """PRO-06: ingreso futuro en USD convertido a MXN con tasa 18.00."""
    db_session.add(
        ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 1), rate=Decimal("18.00"))
    )
    await db_session.commit()
    ctx = await bootstrap_space(client)
    await add_income(client, ctx, "100.00", "2026-07-01", currency="USD")

    body = await forecast(client, ctx, horizon_months=6, cash_adjustment="0")

    usd_in = next(e for e in body["events"] if e["direction"] == "in" and e["date"] == "2026-07-01")
    assert usd_in["amount"] == "1800.00"  # 100 USD × 18.00
    assert usd_in["currency"] == "USD"


@freeze_time("2026-05-20 18:00:00")
async def test_pro03_paid_statement_not_recycled_into_next_projection(client):
    """Bug: un statement ya `paid` se re-sumaba en el pago proyectado siguiente
    porque el filtro solo excluía closed/partially_paid, no paid. Un statement
    cerrado y liquidado por completo no debe re-proyectarse (solo el ciclo
    abierto actual debe alimentar el próximo pago)."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, statement_day=15, payment_due_days=2)
    method_id = card["payment_method_id"]
    debito = ctx["methods"]["Débito"]["id"]

    # Cargo en el ciclo [16-abr, 15-may], cerrado y pagado por completo.
    await charge(client, ctx, method_id, "2026-05-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]
    res = await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "500.00",
            "from_payment_method_id": debito,
            "date": "2026-05-20",
            "statement_id": statement_id,
        },
    )
    assert res.status_code == 201, res.text
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    assert next(s for s in statements if s["id"] == statement_id)["status"] == "paid"

    # Cargo en el ciclo abierto actual [16-may, 15-jun].
    await charge(client, ctx, method_id, "2026-06-10", "300.00")

    with freeze_time("2026-06-20 18:00:00"):
        body = await forecast(client, ctx, horizon_months=2)

    card_dues = [e for e in body["events"] if e["kind"] == "card_due"]
    assert len(card_dues) == 1
    due = card_dues[0]
    assert due["date"] == "2026-07-17"
    assert due["amount"] == "300.00"  # NO debe arrastrar el statement ya pagado (500)


@freeze_time("2026-06-20 18:00:00")
async def test_pro01_readonly_no_statement_materialization(client, db_session):
    """PRO-01: el pronóstico no materializa statements (read-only)."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, statement_day=15, payment_due_days=2)
    await charge(client, ctx, card["payment_method_id"], "2026-06-20", "8000.00")

    before = await db_session.scalar(select(func.count()).select_from(CardStatement))
    await forecast(client, ctx, horizon_months=12)
    after = await db_session.scalar(select(func.count()).select_from(CardStatement))
    assert before == after
