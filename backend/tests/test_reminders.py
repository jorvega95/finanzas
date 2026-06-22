"""Tests de recordatorios (REM-01, REM-01b, REM-02).

Cubre los tres bugs corregidos:
  Bug 1: gastos en meses pasados no deben generar recordatorios inmediatos (REM-01).
  Bug 2: opening_balance debe programar recordatorios futuros (REM-01).
  Bug 3: al pagar, los recordatorios sent también se cancelan (REM-01b).
"""

from freezegun import freeze_time

from tests.conftest import bootstrap_space
from tests.test_cards import charge, close_cycles, create_card

# ---------------------------------------------------------------------------
# Bug 1 — Gastos en meses pasados no deben crear recordatorios inmediatos
# ---------------------------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_rem01_no_past_reminders_on_historical_charge(client):
    """REM-01: cerrar un statement histórico no debe crear recordatorios con
    fire_at en el pasado ni dispararlos inmediatamente al inbox."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]

    # Cargo del 10-may → ciclo [16-abr, 15-may] → due 4-jun → fire_at 1-jun y 3-jun (pasados).
    await charge(client, ctx, method_id, "2026-05-10", "300.00")
    await close_cycles(client, ctx)

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    # Ningún recordatorio debe existir: fire_at < today quedaron descartados (REM-01).
    assert inbox == [], f"Recordatorios inesperados para corte pasado: {inbox}"


# ---------------------------------------------------------------------------
# Bug 2 — Opening balance debe programar recordatorios futuros
# ---------------------------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_rem01_opening_balance_schedules_future_reminders(client):
    """REM-01: al registrar opening_balance se programan recordatorios futuros
    para el statement sintético del corte anterior (TDC-14 + REM-01)."""
    ctx = await bootstrap_space(client)
    # Hoy 20-jun, corte=15 → cutoff anterior=15-jun → due 5-jul → fire_at 2-jul y 4-jul.
    await create_card(client, ctx, opening_balance="1500.00", reminder_days=[3, 1])

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    fire_dates = {r["fire_at"] for r in inbox}
    assert fire_dates == {"2026-07-02", "2026-07-04"}, f"fire_at inesperados: {fire_dates}"
    # Deben estar pending: fire_due_reminders no se ha ejecutado aún.
    assert all(r["status"] == "pending" for r in inbox), (
        f"Statuses inesperados: {[r['status'] for r in inbox]}"
    )


@freeze_time("2026-07-10 18:00:00")
async def test_rem01_opening_balance_no_reminders_when_due_date_passed(client):
    """REM-01: si la due_date del opening_balance ya venció no se crean reminders.
    Hoy 10-jul → due_date = 5-jul (pasado) → fire_at 2-jul y 4-jul también pasados."""
    ctx = await bootstrap_space(client)
    # Corte anterior desde hoy-10-jul: cutoff_on_or_after(10-jul)=15-jul,
    # previous(15-jul)=15-jun → due=5-jul (pasado), fire_at 2-jul y 4-jul (pasados).
    await create_card(client, ctx, opening_balance="1500.00", reminder_days=[3, 1])

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    assert inbox == [], f"Se crearon recordatorios con due_date ya vencida: {inbox}"


@freeze_time("2026-06-20 18:00:00")
async def test_rem01_opening_balance_zeroed_cancels_reminders(client):
    """REM-01: si opening_balance se actualiza a 0, sus reminders se cancelan."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, opening_balance="1500.00", reminder_days=[3, 1])

    inbox_before = (
        await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])
    ).json()
    assert len(inbox_before) == 2  # pending 2-jul y 4-jul

    # Editar a 0 → statement queda pagado y reminders cancelados.
    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"opening_balance": "0"},
    )
    assert res.status_code == 200, res.text

    inbox_after = (
        await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])
    ).json()
    assert all(r["status"] == "canceled" for r in inbox_after), (
        f"Reminders no cancelados: {inbox_after}"
    )


# ---------------------------------------------------------------------------
# Bug 3 — Recordatorios sent deben cancelarse al pagar (REM-01b)
# ---------------------------------------------------------------------------


@freeze_time("2026-07-02 08:00:00")
async def test_rem01b_sent_reminders_canceled_on_payment(client):
    """REM-01b: al pagar un statement se cancelan pending Y sent.
    Usa fecha 2026-07-02 = primer fire_at del corte [16-may, 15-jun] con due 5-jul."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]
    debito = ctx["methods"]["Débito"]["id"]

    # Cargo del 10-jun → ciclo [16-may, 15-jun] → due 5-jul → fire_at 2-jul (hoy) y 4-jul.
    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    assert len(closed) == 1
    statement_id = closed[0]["id"]

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    statuses = {r["status"] for r in inbox}
    # fire_at=2026-07-02 (hoy) debe estar sent; fire_at=2026-07-04 debe estar pending.
    assert "sent" in statuses, f"Falta sent en inbox: {statuses}"
    assert "pending" in statuses, f"Falta pending en inbox: {statuses}"

    # Pago completo → REM-01b: sent y pending deben cancelarse.
    res = await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "500.00",
            "from_payment_method_id": debito,
            "date": "2026-07-02",
            "statement_id": statement_id,
        },
    )
    assert res.status_code == 201, res.text

    inbox2 = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    active = [r for r in inbox2 if r["status"] in ("pending", "sent")]
    assert active == [], f"Quedaron notificaciones activas tras pago: {active}"


@freeze_time("2026-07-02 08:00:00")
async def test_rem01b_partial_payment_keeps_reminders(client):
    """REM-01b: un pago parcial NO cancela los reminders — el statement sigue pendiente."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]
    debito = ctx["methods"]["Débito"]["id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]

    # Pago parcial (solo 200 de 500).
    res = await client.post(
        f"/api/v1/cards/{card['id']}/payments",
        headers=ctx["headers"],
        json={
            "amount": "200.00",
            "from_payment_method_id": debito,
            "date": "2026-07-02",
            "statement_id": statement_id,
        },
    )
    assert res.status_code == 201, res.text

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    # Reminders deben seguir activos (sent o pending): el statement no está pagado.
    active = [r for r in inbox if r["status"] in ("pending", "sent")]
    assert len(active) > 0, "El pago parcial no debería cancelar los reminders"


# ---------------------------------------------------------------------------
# REM-05: descarte (soft-delete) de recordatorios
# ---------------------------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_rem05_dismiss_removes_from_inbox(client):
    """REM-05: descartar un recordatorio lo oculta del inbox (soft-delete)."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    await close_cycles(client, ctx)

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    assert len(inbox) == 2

    # Descartar el primero.
    reminder_id = inbox[0]["id"]
    res = await client.delete(f"/api/v1/cards/notifications/{reminder_id}", headers=ctx["headers"])
    assert res.status_code == 204

    # El inbox ya no lo muestra.
    inbox2 = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    assert len(inbox2) == 1
    assert all(r["id"] != reminder_id for r in inbox2)


@freeze_time("2026-06-20 18:00:00")
async def test_rem05_dismiss_cross_space_404(client):
    """REM-05: no se puede descartar un recordatorio de otro espacio (GLO-05)."""
    ctx_a = await bootstrap_space(client)
    ctx_b = await bootstrap_space(client)

    card = await create_card(client, ctx_a, reminder_days=[3])
    await charge(client, ctx_a, card["payment_method_id"], "2026-06-10", "100.00")
    await close_cycles(client, ctx_a)

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx_a["headers"])).json()
    reminder_id = inbox[0]["id"]

    # Usuario de espacio B intenta descartar recordatorio de A.
    res = await client.delete(
        f"/api/v1/cards/notifications/{reminder_id}", headers=ctx_b["headers"]
    )
    assert res.status_code == 404


@freeze_time("2026-06-20 18:00:00")
async def test_rem05_dismiss_does_not_cancel_statement(client):
    """REM-05: descartar no cancela el statement ni afecta otros reminders."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    # Descartar ambos.
    for n in inbox:
        res = await client.delete(f"/api/v1/cards/notifications/{n['id']}", headers=ctx["headers"])
        assert res.status_code == 204

    # El statement sigue cerrado y pendiente de pago.
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    st = next(s for s in statements if s["id"] == statement_id)
    assert st["status"] == "closed"

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "500.00"


# ---------------------------------------------------------------------------
# REM-02: idempotencia — no se duplican reminders
# ---------------------------------------------------------------------------


@freeze_time("2026-06-20 18:00:00")
async def test_rem02_no_duplicate_reminders(client):
    """REM-02: cerrar ciclos múltiples veces no duplica recordatorios."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")

    # Cerrar dos veces seguidas.
    await close_cycles(client, ctx)
    await close_cycles(client, ctx)

    inbox = (await client.get("/api/v1/cards/notifications/inbox", headers=ctx["headers"])).json()
    # Solo 2 reminders in_app: uno por cada offset (3 y 1 día).
    assert len(inbox) == 2, f"Se duplicaron reminders: {len(inbox)} encontrados"
