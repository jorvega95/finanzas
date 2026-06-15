"""Tests: TXN-08 (transfer balance), TXN-09 (transfer→TDC as payment), TAR-06 (signed_balance)."""

from decimal import Decimal

from freezegun import freeze_time

from tests.conftest import bootstrap_space


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def make_debit(client, ctx, initial_balance="1000.00", allow_overdraft=False, **overrides):
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": ctx["card_type_by_behavior"]["debit"]["id"],
            "alias": overrides.pop("alias", "Débito BBVA"),
            "bank": "BBVA",
            "network": "Visa",
            "last4": overrides.pop("last4", "4321"),
            "initial_balance": initial_balance,
            "allow_overdraft": allow_overdraft,
            **overrides,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def make_credit(client, ctx, **overrides):
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": ctx["card_type_by_behavior"]["credit"]["id"],
            "alias": overrides.pop("alias", "Crédito Banamex"),
            "bank": "Banamex",
            "network": "Mastercard",
            "last4": overrides.pop("last4", "9999"),
            "statement_day": 15,
            "payment_due_days": 20,
            **overrides,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def transfer(client, ctx, from_method_id, to_method_id, amount, date="2026-06-10", **extra):
    return await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "transfer",
            "date": date,
            "amount": amount,
            "currency": "MXN",
            "payment_method_id": from_method_id,
            "payment_method_to_id": to_method_id,
            **extra,
        },
    )


async def charge_credit(client, ctx, method_id, amount, date="2026-06-10"):
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
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def close_cycles(client, ctx):
    res = await client.post("/api/v1/cards/close-cycles", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def get_statements(client, ctx, card_id):
    res = await client.get(f"/api/v1/cards/{card_id}/statements", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def get_card(client, ctx, card_id):
    res = await client.get(f"/api/v1/cards/{card_id}", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# TXN-08: validación de saldo en transferencias desde debit/prepaid
# ---------------------------------------------------------------------------


@freeze_time("2026-06-10 12:00:00")
async def test_txn08_transfer_blocked_when_insufficient_funds(client):
    """TXN-08: transfer desde débito con monto > saldo disponible → 422."""
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="500.00")
    cash = ctx["methods"]["Efectivo"]["id"]
    debit_method = debit["payment_method_id"]

    # saldo=500, transferir 300 → saldo queda 200: ok.
    res = await transfer(client, ctx, debit_method, cash, "300.00")
    assert res.status_code == 201, res.text

    # Saldo restante=200, transferir 201 → insuficiente: 422.
    res = await transfer(client, ctx, debit_method, cash, "201.00")
    assert res.status_code == 422


@freeze_time("2026-06-10 12:00:00")
async def test_txn08_transfer_allowed_with_overdraft(client):
    """TXN-08: allow_overdraft=True permite transferir más del saldo."""
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="100.00", allow_overdraft=True)
    cash = ctx["methods"]["Efectivo"]["id"]

    res = await transfer(client, ctx, debit["payment_method_id"], cash, "500.00")
    assert res.status_code == 201

    detail = await get_card(client, ctx, debit["id"])
    assert Decimal(detail["balance"]) == Decimal("-400.00")


@freeze_time("2026-06-10 12:00:00")
async def test_txn08_transfer_from_non_card_method_no_balance_check(client):
    """TXN-08: origen sin tarjeta vinculada (Efectivo) no requiere validación de saldo."""
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="100.00")
    cash = ctx["methods"]["Efectivo"]["id"]

    # Transferir desde Efectivo (sin card_id) → permitido sin importar el monto.
    res = await transfer(client, ctx, cash, debit["payment_method_id"], "999999.00")
    assert res.status_code == 201


@freeze_time("2026-06-10 12:00:00")
async def test_txn08_prepaid_transfer_balance_check(client):
    """TXN-08: aplica igualmente a tarjetas prepaid."""
    ctx = await bootstrap_space(client)
    prepaid = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": ctx["card_type_by_behavior"]["prepaid"]["id"],
            "alias": "Vales",
            "bank": "Sodexo",
            "network": "Mastercard",
            "last4": "5555",
            "initial_balance": "200.00",
        },
    )
    assert prepaid.status_code == 201
    prepaid = prepaid.json()
    cash = ctx["methods"]["Efectivo"]["id"]

    res = await transfer(client, ctx, prepaid["payment_method_id"], cash, "201.00")
    assert res.status_code == 422

    res = await transfer(client, ctx, prepaid["payment_method_id"], cash, "200.00")
    assert res.status_code == 201


# ---------------------------------------------------------------------------
# TXN-09: transferencia a TDC aplica como pago (paid_amount sube)
# ---------------------------------------------------------------------------


@freeze_time("2026-06-20 12:00:00")
async def test_txn09_transfer_to_credit_applies_as_payment(client):
    """TXN-09: transferencia hacia método de TDC abona a paid_amount del statement."""
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="5000.00")
    credit = await make_credit(client, ctx)

    # Cargo 1000 en la TDC (ciclo cierra el 15, hoy es 20 → ya cerró).
    await charge_credit(client, ctx, credit["payment_method_id"], "1000.00", "2026-06-10")
    await close_cycles(client, ctx)

    statements_before = await get_statements(client, ctx, credit["id"])
    closed = next(s for s in statements_before if s["status"] == "closed")
    assert closed["paid_amount"] == "0.00"
    assert Decimal(closed["computed_total"]) == Decimal("1000.00")

    # Transferir 600 desde débito hacia la TDC.
    res = await transfer(
        client, ctx, debit["payment_method_id"], credit["payment_method_id"], "600.00",
        date="2026-06-20",
    )
    assert res.status_code == 201

    statements_after = await get_statements(client, ctx, credit["id"])
    closed_after = next(s for s in statements_after if s["id"] == closed["id"])
    assert Decimal(closed_after["paid_amount"]) == Decimal("600.00")
    assert closed_after["status"] == "partially_paid"


@freeze_time("2026-06-20 12:00:00")
async def test_txn09_full_payment_marks_statement_paid(client):
    """TXN-09: pago igual al total → statement queda en 'paid'."""
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="5000.00")
    credit = await make_credit(client, ctx)

    await charge_credit(client, ctx, credit["payment_method_id"], "800.00", "2026-06-10")
    await close_cycles(client, ctx)

    res = await transfer(
        client, ctx, debit["payment_method_id"], credit["payment_method_id"], "800.00",
        date="2026-06-20",
    )
    assert res.status_code == 201

    statements = await get_statements(client, ctx, credit["id"])
    closed = next(s for s in statements if s["status"] != "open")
    assert closed["status"] == "paid"


@freeze_time("2026-06-20 12:00:00")
async def test_txn09_auto_selects_oldest_unpaid_statement(client):
    """TXN-09: con dos statements cerrados no pagados, abona al más antiguo.

    Setup: cargo en abril (ciclo A, cierra 15/05) + cargo en mayo (ciclo B, cierra 15/06).
    Al hacer close_cycles en 2026-06-20 quedan dos ciclos cerrados sin pagar.
    """
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="5000.00")
    credit = await make_credit(client, ctx, statement_day=15, last4="1111")

    # Cargo en ciclo A [16/04–15/05] y cargo en ciclo B [16/05–15/06].
    await charge_credit(client, ctx, credit["payment_method_id"], "300.00", "2026-04-20")
    await charge_credit(client, ctx, credit["payment_method_id"], "500.00", "2026-06-10")
    await close_cycles(client, ctx)

    statements = await get_statements(client, ctx, credit["id"])
    closed = sorted(
        [s for s in statements if s["status"] in ("closed", "partially_paid")],
        key=lambda s: s["period_end"],
    )
    assert len(closed) >= 2, f"Expected ≥2 closed, got {len(closed)}: {closed}"

    oldest = closed[0]

    # Pago parcial → debe aplicar al más antiguo.
    res = await transfer(
        client, ctx, debit["payment_method_id"], credit["payment_method_id"], "100.00",
        date="2026-06-20",
    )
    assert res.status_code == 201

    statements_after = await get_statements(client, ctx, credit["id"])
    oldest_after = next(s for s in statements_after if s["id"] == oldest["id"])
    assert Decimal(oldest_after["paid_amount"]) == Decimal("100.00")


@freeze_time("2026-06-20 12:00:00")
async def test_txn09_target_statement_id_overrides_auto_select(client):
    """TXN-09: target_statement_id explícito abona al statement indicado, no al más antiguo."""
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="5000.00")
    credit = await make_credit(client, ctx, statement_day=15, last4="2222")

    # Dos ciclos cerrados: A (cierra 15/05) y B (cierra 15/06).
    await charge_credit(client, ctx, credit["payment_method_id"], "300.00", "2026-04-20")
    await charge_credit(client, ctx, credit["payment_method_id"], "700.00", "2026-06-10")
    await close_cycles(client, ctx)

    statements = await get_statements(client, ctx, credit["id"])
    closed = sorted(
        [s for s in statements if s["status"] in ("closed", "partially_paid")],
        key=lambda s: s["period_end"],
    )
    assert len(closed) >= 2, f"Expected ≥2 closed, got {len(closed)}"
    newest_closed = closed[-1]  # ciclo B (15/06), no el más antiguo

    # Pagamos el ciclo B explícitamente, dejando el ciclo A sin tocar.
    res = await transfer(
        client, ctx, debit["payment_method_id"], credit["payment_method_id"], "200.00",
        date="2026-06-20",
        target_statement_id=newest_closed["id"],
    )
    assert res.status_code == 201

    statements_after = await get_statements(client, ctx, credit["id"])
    newest_after = next(s for s in statements_after if s["id"] == newest_closed["id"])
    assert Decimal(newest_after["paid_amount"]) == Decimal("200.00")

    # El más antiguo NO debe haber sido tocado.
    oldest_after = next(s for s in statements_after if s["id"] == closed[0]["id"])
    assert Decimal(oldest_after["paid_amount"]) == Decimal("0.00")


@freeze_time("2026-06-10 12:00:00")
async def test_txn09_transfer_to_debit_is_plain_transfer(client):
    """TXN-09: transferencia a tarjeta de débito no toca statements."""
    ctx = await bootstrap_space(client)
    debit_a = await make_debit(client, ctx, initial_balance="2000.00", last4="1001")
    debit_b = await make_debit(client, ctx, initial_balance="0.00", last4="1002", alias="B")

    res = await transfer(
        client, ctx, debit_a["payment_method_id"], debit_b["payment_method_id"], "500.00"
    )
    assert res.status_code == 201

    txn = res.json()
    assert txn["statement_id"] is None  # no statement assigned

    detail_a = await get_card(client, ctx, debit_a["id"])
    detail_b = await get_card(client, ctx, debit_b["id"])
    assert Decimal(detail_a["balance"]) == Decimal("1500.00")
    assert Decimal(detail_b["balance"]) == Decimal("500.00")


# ---------------------------------------------------------------------------
# TAR-06: signed_balance
# ---------------------------------------------------------------------------


@freeze_time("2026-06-20 12:00:00")
async def test_tar06_debit_signed_balance_is_positive(client):
    """TAR-06: tarjeta de débito — signed_balance = +saldo disponible."""
    ctx = await bootstrap_space(client)
    debit = await make_debit(client, ctx, initial_balance="1000.00")
    cash = ctx["methods"]["Efectivo"]["id"]

    # Gasto de 200 → saldo = 800.
    await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-10",
            "amount": "200.00",
            "currency": "MXN",
            "category_id": ctx["categories"]["Comida"]["id"],
            "payment_method_id": debit["payment_method_id"],
        },
    )

    detail = await get_card(client, ctx, debit["id"])
    assert detail["signed_balance"] == "800.00"
    assert Decimal(detail["signed_balance"]) > 0


@freeze_time("2026-06-20 12:00:00")
async def test_tar06_credit_signed_balance_is_negative(client):
    """TAR-06: tarjeta de crédito — signed_balance = -(deuda total TDC-09 a+b+c)."""
    ctx = await bootstrap_space(client)
    credit = await make_credit(client, ctx)

    # Cargo en ciclo cerrado (a) y cargo en ciclo abierto (b).
    await charge_credit(client, ctx, credit["payment_method_id"], "500.00", "2026-06-10")
    await close_cycles(client, ctx)  # el cargo de 500 queda en ciclo cerrado
    await charge_credit(client, ctx, credit["payment_method_id"], "300.00", "2026-06-18")

    detail = await get_card(client, ctx, credit["id"])
    # signed_balance debe ser negativo y su valor absoluto == deuda total.
    assert detail["signed_balance"] is not None
    signed = Decimal(detail["signed_balance"])
    assert signed < 0
    # Deuda total = 500 (cerrado) + 300 (en curso) = 800.
    assert signed == Decimal("-800.00")


@freeze_time("2026-06-20 12:00:00")
async def test_tar06_credit_without_statement_day_returns_null(client):
    """TAR-06: TDC sin statement_day configurado → signed_balance = null."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/cards",
        headers=ctx["headers"],
        json={
            "card_type_id": ctx["card_type_by_behavior"]["credit"]["id"],
            "alias": "TDC Incompleta",
            "bank": "HSBC",
            "network": "Visa",
            "last4": "0000",
            # Sin statement_day → no cycle-ready (TDC-15)
        },
    )
    assert res.status_code == 201
    card = res.json()

    detail = await get_card(client, ctx, card["id"])
    assert detail["signed_balance"] is None


@freeze_time("2026-06-20 12:00:00")
async def test_tar06_credit_no_debt_signed_balance_is_zero(client):
    """TAR-06: TDC sin ninguna deuda → signed_balance = 0.00."""
    ctx = await bootstrap_space(client)
    credit = await make_credit(client, ctx)

    detail = await get_card(client, ctx, credit["id"])
    assert detail["signed_balance"] == "0.00"
