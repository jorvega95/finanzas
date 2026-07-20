"""Tests de recordatorios y centro de notificaciones (REM-01..REM-07).

Cubre los tres bugs corregidos:
  Bug 1: gastos en meses pasados no deben generar recordatorios inmediatos (REM-01).
  Bug 2: opening_balance debe programar recordatorios futuros (REM-01).
  Bug 3: al pagar, los recordatorios sent también se cancelan (REM-01b).

Y el centro de notificaciones in-app (OPP-01):
  REM-06: `GET /notifications` solo muestra avisos disparados y no descartados;
          `GET /notifications/history` conserva todos los estados para auditoría.
  REM-07: `read_at` (badge) es independiente del descarte.
"""

from freezegun import freeze_time

from tests.conftest import bootstrap_space
from tests.test_cards import charge, close_cycles, create_card

# ---------------------------------------------------------------------------
# Helpers del centro de notificaciones (REM-06)
# ---------------------------------------------------------------------------


async def inbox(client, ctx) -> list[dict]:
    """REM-06: lo que el usuario ve en la campana."""
    res = await client.get("/api/v1/notifications", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def history(client, ctx, channel: str = "in_app") -> list[dict]:
    """REM-06: auditoría — todos los estados. Por defecto solo canal in_app."""
    res = await client.get("/api/v1/notifications/history", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return [n for n in res.json() if n["channel"] == channel]


async def unread(client, ctx) -> int:
    """REM-07: badge de la campana."""
    res = await client.get("/api/v1/notifications/unread-count", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return int(res.json()["unread"])


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

    # Ningún recordatorio debe existir siquiera: fire_at < today quedó descartado (REM-01).
    assert await history(client, ctx) == []
    assert await inbox(client, ctx) == []


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

    programmed = await history(client, ctx)
    fire_dates = {r["fire_at"] for r in programmed}
    assert fire_dates == {"2026-07-02", "2026-07-04"}, f"fire_at inesperados: {fire_dates}"
    # Deben estar pending: fire_due_reminders no se ha ejecutado aún.
    assert all(r["status"] == "pending" for r in programmed), (
        f"Statuses inesperados: {[r['status'] for r in programmed]}"
    )
    # REM-06: un aviso programado a futuro NO es una notificación todavía.
    assert await inbox(client, ctx) == []
    assert await unread(client, ctx) == 0


@freeze_time("2026-07-10 18:00:00")
async def test_rem01_opening_balance_no_reminders_when_due_date_passed(client):
    """REM-01: si la due_date del opening_balance ya venció no se crean reminders.
    Hoy 10-jul → due_date = 5-jul (pasado) → fire_at 2-jul y 4-jul también pasados."""
    ctx = await bootstrap_space(client)
    # Corte anterior desde hoy-10-jul: cutoff_on_or_after(10-jul)=15-jul,
    # previous(15-jul)=15-jun → due=5-jul (pasado), fire_at 2-jul y 4-jul (pasados).
    await create_card(client, ctx, opening_balance="1500.00", reminder_days=[3, 1])

    assert await history(client, ctx) == []


@freeze_time("2026-06-20 18:00:00")
async def test_rem01_opening_balance_zeroed_cancels_reminders(client):
    """REM-01: si opening_balance se actualiza a 0, sus reminders se cancelan."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, opening_balance="1500.00", reminder_days=[3, 1])

    assert len(await history(client, ctx)) == 2  # pending 2-jul y 4-jul

    # Editar a 0 → statement queda pagado y reminders cancelados.
    res = await client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=ctx["headers"],
        json={"opening_balance": "0"},
    )
    assert res.status_code == 200, res.text

    after = await history(client, ctx)
    assert all(r["status"] == "canceled" for r in after), f"Reminders no cancelados: {after}"


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

    statuses = {r["status"] for r in await history(client, ctx)}
    # fire_at=2026-07-02 (hoy) debe estar sent; fire_at=2026-07-04 debe estar pending.
    assert statuses == {"sent", "pending"}, f"Statuses inesperados: {statuses}"
    # REM-06: solo el disparado llega al inbox.
    visible = await inbox(client, ctx)
    assert len(visible) == 1 and visible[0]["fire_at"] == "2026-07-02"

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

    active = [r for r in await history(client, ctx) if r["status"] in ("pending", "sent")]
    assert active == [], f"Quedaron notificaciones activas tras pago: {active}"
    # REM-01b: el aviso desaparece de la campana en cuanto se paga.
    assert await inbox(client, ctx) == []
    assert await unread(client, ctx) == 0


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

    # Reminders deben seguir activos (sent o pending): el statement no está pagado.
    active = [r for r in await history(client, ctx) if r["status"] in ("pending", "sent")]
    assert len(active) > 0, "El pago parcial no debería cancelar los reminders"
    assert len(await inbox(client, ctx)) == 1


# ---------------------------------------------------------------------------
# REM-05: descarte (soft-delete) de recordatorios
# ---------------------------------------------------------------------------


@freeze_time("2026-07-02 08:00:00")
async def test_rem05_dismiss_removes_from_inbox(client):
    """REM-05: descartar un recordatorio lo oculta del inbox (soft-delete),
    pero se conserva en el historial para auditoría."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    await close_cycles(client, ctx)

    visible = await inbox(client, ctx)
    assert len(visible) == 1
    reminder_id = visible[0]["id"]

    res = await client.delete(f"/api/v1/notifications/{reminder_id}", headers=ctx["headers"])
    assert res.status_code == 204

    assert await inbox(client, ctx) == []
    # Soft-delete: sigue en el historial marcado como dismissed.
    archived = next(r for r in await history(client, ctx) if r["id"] == reminder_id)
    assert archived["status"] == "dismissed"


@freeze_time("2026-07-02 08:00:00")
async def test_rem05_dismiss_cross_space_404(client):
    """REM-05: no se puede descartar un recordatorio de otro espacio (GLO-05)."""
    ctx_a = await bootstrap_space(client)
    ctx_b = await bootstrap_space(client)

    card = await create_card(client, ctx_a, reminder_days=[3])
    await charge(client, ctx_a, card["payment_method_id"], "2026-06-10", "100.00")
    await close_cycles(client, ctx_a)

    reminder_id = (await inbox(client, ctx_a))[0]["id"]

    # Usuario de espacio B intenta descartar recordatorio de A.
    res = await client.delete(f"/api/v1/notifications/{reminder_id}", headers=ctx_b["headers"])
    assert res.status_code == 404
    # Y tampoco lo ve en su propio inbox (GLO-05).
    assert await inbox(client, ctx_b) == []


@freeze_time("2026-07-02 08:00:00")
async def test_rem05_dismiss_does_not_cancel_statement(client):
    """REM-05: descartar no cancela el statement ni afecta otros reminders."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    method_id = card["payment_method_id"]

    await charge(client, ctx, method_id, "2026-06-10", "500.00")
    closed = await close_cycles(client, ctx)
    statement_id = closed[0]["id"]

    for n in await inbox(client, ctx):
        res = await client.delete(f"/api/v1/notifications/{n['id']}", headers=ctx["headers"])
        assert res.status_code == 204

    # El statement sigue cerrado y pendiente de pago.
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    st = next(s for s in statements if s["id"] == statement_id)
    assert st["status"] == "closed"

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["statement_balance"] == "500.00"

    # El recordatorio aún pendiente de disparar no se ve afectado (REM-05).
    pending = [r for r in await history(client, ctx) if r["status"] == "pending"]
    assert len(pending) == 1


# ---------------------------------------------------------------------------
# REM-06/REM-07: inbox in-app, badge de no leídos y marcado de lectura
# ---------------------------------------------------------------------------


@freeze_time("2026-07-02 08:00:00")
async def test_rem07_unread_badge_and_mark_one_read(client):
    """REM-07: leer un aviso baja el badge pero lo deja visible en el inbox."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, reminder_days=[3, 1])
    await charge(client, ctx, card["payment_method_id"], "2026-06-10", "500.00")
    await close_cycles(client, ctx)

    assert await unread(client, ctx) == 1
    notification = (await inbox(client, ctx))[0]
    assert notification["read_at"] is None

    res = await client.post(
        f"/api/v1/notifications/{notification['id']}/read", headers=ctx["headers"]
    )
    assert res.status_code == 200, res.text
    assert res.json()["read_at"] is not None
    # Leído ≠ descartado: el aviso sigue en la campana.
    assert res.json()["status"] == "sent"

    assert await unread(client, ctx) == 0
    still_visible = await inbox(client, ctx)
    assert len(still_visible) == 1 and still_visible[0]["read_at"] is not None


@freeze_time("2026-07-02 08:00:00")
async def test_rem07_read_all_is_idempotent(client):
    """REM-07: marcar todo leído es idempotente y no altera `status`."""
    ctx = await bootstrap_space(client)
    # Dos tarjetas con el mismo corte → dos avisos disparados hoy (fire_at = due − 3).
    for alias in ("Oro", "Platino"):
        card = await create_card(client, ctx, alias=alias, reminder_days=[3])
        await charge(client, ctx, card["payment_method_id"], "2026-06-10", "500.00")
    await close_cycles(client, ctx)

    assert len(await inbox(client, ctx)) == 2
    assert await unread(client, ctx) == 2

    first = await client.post("/api/v1/notifications/read-all", headers=ctx["headers"])
    assert first.status_code == 200 and first.json()["marked"] == 2
    second = await client.post("/api/v1/notifications/read-all", headers=ctx["headers"])
    assert second.json()["marked"] == 0, "read-all debe ser idempotente"

    assert await unread(client, ctx) == 0
    assert all(n["status"] == "sent" for n in await inbox(client, ctx))


@freeze_time("2026-07-02 08:00:00")
async def test_rem06_inbox_is_scoped_to_active_space(client):
    """REM-06/GLO-05: el inbox y el badge solo cuentan el espacio activo."""
    ctx_a = await bootstrap_space(client)
    ctx_b = await bootstrap_space(client)

    card = await create_card(client, ctx_a, reminder_days=[3])
    await charge(client, ctx_a, card["payment_method_id"], "2026-06-10", "500.00")
    await close_cycles(client, ctx_a)

    assert await unread(client, ctx_a) == 1
    assert await unread(client, ctx_b) == 0
    assert await inbox(client, ctx_b) == []


@freeze_time("2026-07-02 08:00:00")
async def test_rem07_read_cross_space_404(client):
    """REM-07: marcar leído un aviso de otro espacio devuelve 404 (GLO-05)."""
    ctx_a = await bootstrap_space(client)
    ctx_b = await bootstrap_space(client)

    card = await create_card(client, ctx_a, reminder_days=[3])
    await charge(client, ctx_a, card["payment_method_id"], "2026-06-10", "500.00")
    await close_cycles(client, ctx_a)
    reminder_id = (await inbox(client, ctx_a))[0]["id"]

    res = await client.post(f"/api/v1/notifications/{reminder_id}/read", headers=ctx_b["headers"])
    assert res.status_code == 404


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

    # Solo 2 reminders in_app: uno por cada offset (3 y 1 día).
    in_app = await history(client, ctx)
    assert len(in_app) == 2, f"Se duplicaron reminders: {len(in_app)} encontrados"
    # Y sus gemelos por email (REM-04), tampoco duplicados.
    assert len(await history(client, ctx, channel="email")) == 2
