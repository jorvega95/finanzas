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
    # MSI-05: cuota 1 (15-jun) en ciclo pasado (current_cutoff=15-jul) → paid;
    # cuota 2 (15-jul) en ciclo actual → charged; cuota 3 (15-ago) → pending.
    assert summary["paid_count"] == 1
    assert summary["charged_count"] == 1
    assert summary["pending_count"] == 1
    assert summary["remaining_amount"] == "666.67"

    # MSI-02: 333.33 × 2 + 333.34.
    amounts = [i["amount"] for i in summary["installments"]]
    assert amounts == ["333.33", "333.33", "333.34"]
    # MSI-04: estimated_charge_date = period_end (día de corte) del ciclo de cada cuota.
    # Cuota 1 → corte del 15-jun (ciclo al que se asigna la compra del 10-jun).
    # Cuota 2 → corte del 15-jul; cuota 3 → corte del 15-ago.
    dates = [i["estimated_charge_date"] for i in summary["installments"]]
    assert dates == ["2026-06-15", "2026-07-15", "2026-08-15"]

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

    # TDC-09: cuota 2 charged en ciclo abierto (15-jul); cuotas 3-12 pending.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "1000.00"
    assert detail["debt"]["current_cycle_spend"] == "1000.00"
    assert detail["debt"]["committed_msi"] == "10000.00"
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

    # MSI-05: cuota 1 (15-jun) en ciclo pasado → paid; cuota 2 (15-jul) → charged;
    # cuota 3 → pending.
    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    statuses = [i["status"] for i in plans[0]["installments"]]
    assert statuses == ["paid", "charged", "pending"]

    # Pagar el statement de junio (cuota 1=300) no afecta cuota 2 (en statement de julio).
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
    assert statuses == ["paid", "charged", "pending"]
    assert plans[0]["remaining_amount"] == "600.00"  # MSI-06: charged + pending


@freeze_time("2026-06-20 18:00:00")
async def test_msi06_projection_month_by_card(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "600.00")
    await make_plan(client, ctx, txn["id"], 3)

    rows = (await client.get("/api/v1/installment-plans/projection", headers=ctx["headers"])).json()
    # Cuota 1 (15-jun) → paid; cuota 2 (15-jul) → charged; cuota 3 (15-ago) → pending.
    # La proyección solo incluye cuotas pending.
    assert [(r["month"], r["amount"]) for r in rows] == [
        ("2026-08", "200.00"),
    ]
    assert all(r["card_alias"] == "BBVA Azul" for r in rows)


@freeze_time("2026-06-20 18:00:00")
async def test_msi07_settle_early(client):
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)
    txn = await charge(client, ctx, card["payment_method_id"], "2026-06-10", "1200.00")
    plan = await make_plan(client, ctx, txn["id"], 12)
    await close_cycles(client, ctx)  # cuota 1 paid (ciclo pasado), cuota 2 charged (ciclo actual)

    res = await client.post(
        f"/api/v1/installment-plans/{plan['id']}/settle", headers=ctx["headers"]
    )
    assert res.status_code == 200
    assert res.json()["status"] == "settled_early"

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    statuses = [i["status"] for i in plans[0]["installments"]]
    # settle cancela las 10 cuotas pending (3-12); cuota 1 paid y cuota 2 charged, intactas.
    assert statuses.count("canceled") == 10
    assert statuses.count("charged") == 1
    assert statuses.count("paid") == 1

    # Cargo único por las 10 cuotas (1000) + cuota 2 charged (100) = 1100 en ciclo abierto.
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
async def test_msi01_old_transaction_past_installments_are_paid(client):
    """MSI-01: una compra de ciclos pasados genera cuotas paid, plan completed."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

    # Transacción del 05/03/2026 (3 ciclos atrás, corte=15).
    # charge_dates = [2026-03-15, 2026-04-15, 2026-05-15]
    # current_cutoff = cutoff_on_or_after(2026-06-20, day=15) = 2026-07-15
    # Todas las cuotas < current_cutoff → todas paid → plan completed.
    txn = await charge(client, ctx, card["payment_method_id"], "2026-03-05", "900.00", "Refri")
    await make_plan(client, ctx, txn["id"], 3)

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    summary = plans[0]

    dates = [i["estimated_charge_date"] for i in summary["installments"]]
    assert dates == ["2026-03-15", "2026-04-15", "2026-05-15"]

    statuses = [i["status"] for i in summary["installments"]]
    assert statuses == ["paid", "paid", "paid"]
    assert summary["plan"]["status"] == "completed"
    assert summary["paid_count"] == 3
    assert summary["charged_count"] == 0
    assert summary["pending_count"] == 0
    assert summary["remaining_amount"] == "0.00"


@freeze_time("2026-04-16 18:00:00")
async def test_msi01_old_transaction_mixed_statuses(client):
    """MSI-01: cuotas de ciclos pasados paid, cuota del ciclo actual charged, futuras pending."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

    # Transacción 05/03/2026, hoy 16/04/2026, corte=15.
    # charge_dates = [2026-03-15, 2026-04-15, 2026-05-15, 2026-06-15]
    # current_cutoff = cutoff_on_or_after(2026-04-16, day=15) = 2026-05-15
    # cuota 1 (03-15) < 05-15 → paid
    # cuota 2 (04-15) < 05-15 → paid
    # cuota 3 (05-15) == 05-15 → charged (ciclo actual)
    # cuota 4 (06-15) > 05-15 → pending
    txn = await charge(client, ctx, card["payment_method_id"], "2026-03-05", "1200.00", "Tele")
    await make_plan(client, ctx, txn["id"], 4)

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    summary = plans[0]

    statuses = [i["status"] for i in summary["installments"]]
    assert statuses == ["paid", "paid", "charged", "pending"]
    assert summary["paid_count"] == 2
    assert summary["charged_count"] == 1
    assert summary["pending_count"] == 1
    assert summary["plan"]["status"] == "active"
    # remaining = charged + pending = 300 + 300 = 600
    assert summary["remaining_amount"] == "600.00"


@freeze_time("2026-06-15 18:00:00")
async def test_msi10_register_current_installment(client):
    """MSI-10 charged=True: cuota N paid (ya en opening_balance); N+1 charged en ciclo en curso."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)  # corte día 15

    # Hoy es 2026-06-15 (día de corte).
    # anchor_cutoff = 2026-06-15 (coa == today).
    # Cuota 6: 2026-06-15 → paid (ya en opening_balance).
    # Cuota 7: 2026-07-15 → charged en statement abierto (ciclo en curso).
    # Cuotas 8-12: pending.
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={
            "description": "Smart TV",
            "monthly_amount": "2692.00",
            "currency": "MXN",
            "credit_card_id": card["id"],
            "current_number": 6,
            "total_months": 12,
            "category_id": ctx["categories"]["Otros"]["id"],
            "current_is_charged": True,
        },
    )
    assert res.status_code == 201, res.text
    plan = res.json()
    assert plan["status"] == "active"
    assert plan["total_amount"] == "32304.00"

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    assert len(plans) == 1
    summary = plans[0]
    assert summary["description"] == "Smart TV"
    # Cuotas 1-6 paid; cuota 7 charged; cuotas 8-12 pending.
    assert summary["paid_count"] == 6
    assert summary["charged_count"] == 1
    assert summary["pending_count"] == 5
    # remaining = charged(1) + pending(5) = 6 × 2692.00
    assert summary["remaining_amount"] == "16152.00"
    # MSI-02: Σ cuotas == 32304.00
    amounts = [float(i["amount"]) for i in summary["installments"]]
    assert abs(sum(amounts) - 32304.0) < 0.01

    dates = [i["estimated_charge_date"] for i in summary["installments"]]
    # Ancla en 2026-06-15 (cuota 6); cuota 7 = 2026-07-15 (ciclo en curso).
    assert dates[0] == "2026-01-15"  # cuota 1 (paid, 5 ciclos atrás del ancla)
    assert dates[5] == "2026-06-15"  # cuota 6 (paid, anchor_cutoff)
    assert dates[6] == "2026-07-15"  # cuota 7 (charged, ciclo en curso)
    assert dates[11] == "2026-12-15"  # cuota 12 (última, pending)
    # MSI-06: projected_payment_date posterior al último cobro.
    assert summary["projected_payment_date"] > summary["projected_payoff"]

    # Cuota 7 charged debe aparecer en current_cycle_spend, no en committed_msi.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "2692.00"
    assert detail["debt"]["committed_msi"] == "13460.00"  # 5 × 2692


@freeze_time("2026-06-15 18:00:00")
async def test_msi10_pending_current_installment(client):
    """MSI-10 charged=False: cuota N charged en ciclo en curso; previas paid."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

    # current_is_charged=False: anchor_cutoff = next_cutoff(2026-06-15) = 2026-07-15.
    # Cuota 2 (N): 2026-07-15 → charged en statement abierto del ciclo en curso.
    # Cuota 1 (paid). Cuotas 3-6 (pending).
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={
            "description": "Refrigerador",
            "monthly_amount": "2505.00",
            "currency": "MXN",
            "credit_card_id": card["id"],
            "current_number": 2,
            "total_months": 6,
            "category_id": ctx["categories"]["Otros"]["id"],
            "current_is_charged": False,
        },
    )
    assert res.status_code == 201, res.text

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    summary = plans[0]
    assert summary["paid_count"] == 1
    assert summary["charged_count"] == 1  # cuota 2 en ciclo en curso
    assert summary["pending_count"] == 4
    # remaining = charged(1) + pending(4) = 5 × 2505 = 12525.00
    assert summary["remaining_amount"] == "12525.00"
    dates = [i["estimated_charge_date"] for i in summary["installments"]]
    # anchor_cutoff=15-jul (siguiente corte cuando charged=False y hoy=15-jun es cutoff).
    assert dates[0] == "2026-06-15"  # cuota 1 (paid, ciclo anterior al ancla)
    assert dates[1] == "2026-07-15"  # cuota 2 (charged, anchor_cutoff = ciclo en curso)
    assert dates[2] == "2026-08-15"  # cuota 3 (pending)

    # Cuota 2 charged debe aparecer en current_cycle_spend.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "2505.00"
    assert detail["debt"]["committed_msi"] == "10020.00"  # 4 × 2505


@freeze_time("2026-06-15 18:00:00")
async def test_msi10_projected_payment_date(client):
    """MSI-06: projected_payment_date = due_date_for(projected_payoff, spec)."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)  # corte 15, payment_due_days=20

    # current_number=3, total_months=3, charged → N==M: todas paid, plan completed.
    # anchor_cutoff=2026-06-15. Cuota 3: 2026-06-15. Cuota 2: 2026-05-15. Cuota 1: 2026-04-15.
    # projected_payoff = max = 2026-06-15.
    # projected_payment_date = 2026-06-15 + 20d = 2026-07-05.
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={
            "description": "Lavadora",
            "monthly_amount": "747.00",
            "currency": "MXN",
            "credit_card_id": card["id"],
            "current_number": 3,
            "total_months": 3,
            "category_id": ctx["categories"]["Otros"]["id"],
            "current_is_charged": True,
        },
    )
    assert res.status_code == 201, res.text

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    summary = plans[0]
    # N==M con charged=True: todas las cuotas paid, plan completed de inmediato.
    assert summary["plan"]["status"] == "completed"
    assert summary["paid_count"] == 3
    assert summary["charged_count"] == 0
    assert summary["pending_count"] == 0
    assert summary["remaining_amount"] == "0.00"
    assert summary["projected_payoff"] == "2026-06-15"
    assert summary["projected_payment_date"] == "2026-07-05"


@freeze_time("2026-06-15 18:00:00")
async def test_msi10_validations(client):
    """MSI-10: validaciones básicas de registro por cuota en curso."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

    base = {
        "description": "Test",
        "monthly_amount": "500.00",
        "currency": "MXN",
        "credit_card_id": card["id"],
        "current_number": 3,
        "total_months": 6,
        "category_id": ctx["categories"]["Otros"]["id"],
        "current_is_charged": True,
    }

    # total_months < 2 → falla en schema (ge=2).
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={**base, "total_months": 1},
    )
    assert res.status_code == 422

    # current_number > total_months → falla en servicio.
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={**base, "current_number": 7, "total_months": 6},
    )
    assert res.status_code == 422

    # Moneda distinta a la tarjeta (MSI-09).
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={**base, "currency": "USD"},
    )
    assert res.status_code == 422


@freeze_time("2026-06-20 18:00:00")
async def test_msi10_anchor_off_cutoff_day(client):
    """MSI-10: cuando hoy NO es día de corte, el ancla debe resolverse al
    corte correcto, no al próximo futuro.

    Tarjeta corte=15. Hoy=20-jun (entre cortes).
    cutoff_on_or_after(20-jun) = 15-jul (próximo), NO el 15-jun (cerrado).

    charged=True  → ancla = 15-jun  (ciclo cerrado may-16 – jun-15)
    charged=False → ancla = 15-jul  (ciclo abierto jun-16 – jul-15)
    """
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)  # corte día 15

    # --- charged=True: cuota en el ÚLTIMO estado de cuenta cerrado (15-jun) ---
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={
            "description": "Aire acondicionado",
            "monthly_amount": "1000.00",
            "currency": "MXN",
            "credit_card_id": card["id"],
            "current_number": 2,
            "total_months": 4,
            "category_id": ctx["categories"]["Otros"]["id"],
            "current_is_charged": True,
        },
    )
    assert res.status_code == 201, res.text
    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    summary = plans[0]
    # charged=True: anchor_cutoff = previous_cutoff(15-jul) = 15-jun (period_end).
    dates = [i["estimated_charge_date"] for i in summary["installments"]]
    assert dates[0] == "2026-05-15"  # cuota 1 (paid, corte anterior al ancla)
    assert dates[1] == "2026-06-15", f"cuota 2 debería anclar en 15-jun, no {dates[1]}"
    assert dates[2] == "2026-07-15"  # cuota 3 (pending)
    assert dates[3] == "2026-08-15"  # cuota 4 (pending)
    # Con new semantics: cuota 1 paid, cuota 2 paid, cuota 3 charged, cuota 4 pending.
    assert summary["paid_count"] == 2
    assert summary["charged_count"] == 1
    assert summary["pending_count"] == 1

    # Borrar el plan para el siguiente sub-test (fallará porque hay cuotas paid,
    # pero el test ignora el status y continúa con el siguiente sub-test).
    txn_id = plans[0]["plan"]["transaction_id"]
    await client.delete(f"/api/v1/transactions/{txn_id}", headers=ctx["headers"])

    # --- charged=False: cuota en el ciclo ACTUALMENTE ABIERTO (cierra 15-jul) ---
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={
            "description": "Lavadora",
            "monthly_amount": "800.00",
            "currency": "MXN",
            "credit_card_id": card["id"],
            "current_number": 2,
            "total_months": 4,
            "category_id": ctx["categories"]["Otros"]["id"],
            "current_is_charged": False,
        },
    )
    assert res.status_code == 201, res.text
    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    # Hay dos planes: Lavadora (más reciente) aparece primero.
    summary = next(p for p in plans if p["description"] == "Lavadora")
    # charged=False: anchor_cutoff = coa = 15-jul (ciclo abierto jun-16 – jul-15).
    dates = [i["estimated_charge_date"] for i in summary["installments"]]
    assert dates[0] == "2026-06-15"  # cuota 1 (paid, corte anterior al ancla)
    assert dates[1] == "2026-07-15", f"cuota 2 debería anclar en 15-jul, no {dates[1]}"
    assert dates[2] == "2026-08-15"  # cuota 3 (pending)
    assert dates[3] == "2026-09-15"  # cuota 4 (pending)
    # Con new semantics: cuota 1 paid, cuota 2 charged en ciclo en curso, cuotas 3-4 pending.
    assert summary["paid_count"] == 1
    assert summary["charged_count"] == 1
    assert summary["pending_count"] == 2


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


@freeze_time("2026-06-20 18:00:00")
async def test_msi10_n_equals_m_charged_completes_plan(client):
    """MSI-10 N==M con charged=True: todas las cuotas paid, plan completed al crearse."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)  # corte 15

    # current_number=2, total_months=2, charged=True.
    # anchor_cutoff = previous_cutoff(15-jul) = 15-jun.
    # Cuota 1: 2026-05-15 (paid). Cuota 2: 2026-06-15 (paid, N==M).
    # No existe cuota N+1 → plan completed.
    res = await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={
            "description": "Último MSI",
            "monthly_amount": "500.00",
            "currency": "MXN",
            "credit_card_id": card["id"],
            "current_number": 2,
            "total_months": 2,
            "category_id": ctx["categories"]["Otros"]["id"],
            "current_is_charged": True,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "completed"

    plans = (await client.get("/api/v1/installment-plans", headers=ctx["headers"])).json()
    summary = plans[0]
    assert summary["plan"]["status"] == "completed"
    assert summary["paid_count"] == 2
    assert summary["charged_count"] == 0
    assert summary["pending_count"] == 0
    assert summary["remaining_amount"] == "0.00"

    # Plan completado → no debe afectar ningún total de deuda.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "0.00"
    assert detail["debt"]["committed_msi"] == "0.00"


@freeze_time("2026-06-20 18:00:00")
async def test_msi10_close_cycles_idempotent_after_backfill(client):
    """Job de cierre no duplica cuotas charged con statement_id ya asignado (MSI-10)."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)  # corte 15

    # charged=False: cuota 2 = 15-jul (ciclo abierto), cuotas 3-4 pending.
    await client.post(
        "/api/v1/installment-plans/backfill",
        headers=ctx["headers"],
        json={
            "description": "Bocina",
            "monthly_amount": "600.00",
            "currency": "MXN",
            "credit_card_id": card["id"],
            "current_number": 2,
            "total_months": 4,
            "category_id": ctx["categories"]["Otros"]["id"],
            "current_is_charged": False,
        },
    )
    detail_before = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    cycle_before = detail_before["debt"]["current_cycle_spend"]

    # Cerrar ciclos no debe cambiar el ciclo en curso (cuota 2 ya está charged).
    await close_cycles(client, ctx)

    detail_after = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail_after["debt"]["current_cycle_spend"] == cycle_before
