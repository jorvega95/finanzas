"""Suscripciones, pruebas y servicios variables: REC-06b..REC-13, REM-08.

Incluye el caso de prueba obligatorio 20."""

import uuid
from datetime import date
from decimal import Decimal

from freezegun import freeze_time
from sqlalchemy import select

from app.core.config import settings
from app.models.fx import ExchangeRate
from app.models.reminders import Reminder, ReminderChannel, ReminderKind, ReminderStatus
from app.models.spaces import Space
from app.services import desktop
from app.services.reminders import fire_desktop_reminders
from tests.conftest import bootstrap_space
from tests.test_accounts import add_member

RULES = "/api/v1/recurring-rules"


def sub_payload(ctx, **overrides):
    base = {
        "kind": "subscription",
        "type": "expense",
        "amount": "20.00",
        "currency": "USD",
        "description": "Claude",
        "category_id": ctx["categories"]["Entretenimiento"]["id"],
        "account_id": ctx["accounts"]["Débito"]["id"],  # MXN
        "frequency": "monthly",
        "start_date": "2026-07-21",
    }
    base.update(overrides)
    return base


async def add_rate(db_session, day: date, rate: str) -> None:
    db_session.add(ExchangeRate(base="USD", quote="MXN", date=day, rate=Decimal(rate)))
    await db_session.commit()


async def create_rule(client, ctx, **overrides) -> dict:
    res = await client.post(RULES, headers=ctx["headers"], json=sub_payload(ctx, **overrides))
    assert res.status_code == 201, res.text
    return res.json()


async def generate(client, ctx) -> int:
    res = await client.post(f"{RULES}/generate", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()["created"]


async def rule_txns(client, ctx, rule_id: str) -> list[dict]:
    res = await client.get("/api/v1/transactions?page_size=100", headers=ctx["headers"])
    return [t for t in res.json()["items"] if t["recurring_rule_id"] == rule_id]


async def reminders_of(db_session, rule_id: str) -> list[Reminder]:
    db_session.expire_all()
    rows = await db_session.execute(
        select(Reminder).where(Reminder.recurring_rule_id == uuid.UUID(rule_id))
    )
    return list(rows.scalars().all())


# --- Caso obligatorio 20 / REC-08 ------------------------------------------


async def test_rec08_usd_price_waits_for_today_rate(client, db_session):
    """Caso 20: el cobro de hoy en USD espera la tasa de hoy; luego se genera
    en MXN con el precio original y re-correr no duplica."""
    with freeze_time("2026-07-21 06:35:00"):  # 00:35 en CDMX
        ctx = await bootstrap_space(client)
        await add_rate(db_session, date(2026, 7, 20), "18.00")
        rule = await create_rule(client, ctx)
        assert await generate(client, ctx) == 0

        await add_rate(db_session, date(2026, 7, 21), "18.50")
        assert await generate(client, ctx) == 1
        assert await generate(client, ctx) == 0

        [txn] = await rule_txns(client, ctx, rule["id"])
        assert txn["currency"] == "MXN"  # TAR-10
        assert Decimal(txn["amount"]) == Decimal("370.00")
        assert Decimal(txn["original_amount"]) == Decimal("20.00")
        assert txn["original_currency"] == "USD"
        assert txn["needs_review"] is True  # REC-03


async def test_rec08_catchup_uses_rate_of_each_date(client, db_session):
    """Caso 20: tras días sin correr, cada ocurrencia pasada usa la tasa de su
    fecha (o la previa más cercana), no la de hoy."""
    with freeze_time("2026-08-24 18:00:00"):
        ctx = await bootstrap_space(client)
        await add_rate(db_session, date(2026, 7, 20), "18.00")
        await add_rate(db_session, date(2026, 7, 21), "18.50")
        await add_rate(db_session, date(2026, 8, 21), "19.00")
        await add_rate(db_session, date(2026, 8, 24), "20.00")
        rule = await create_rule(client, ctx)
        assert await generate(client, ctx) == 2
        amounts = {
            t["date"]: Decimal(t["amount"]) for t in await rule_txns(client, ctx, rule["id"])
        }
        assert amounts == {"2026-07-21": Decimal("370.00"), "2026-08-21": Decimal("380.00")}


async def test_rec08_same_currency_has_no_original(client, db_session):
    with freeze_time("2026-07-21 18:00:00"):
        ctx = await bootstrap_space(client)
        rule = await create_rule(client, ctx, amount="129.00", currency="MXN")
        assert await generate(client, ctx) == 1
        [txn] = await rule_txns(client, ctx, rule["id"])
        assert Decimal(txn["amount"]) == Decimal("129.00")
        assert txn["original_amount"] is None


@freeze_time("2026-07-21 18:00:00")
async def test_rec07_08_11_validations(client):
    ctx = await bootstrap_space(client)
    income_cat = ctx["income_categories"]["Otros"]["id"]

    async def post(**overrides):
        return await client.post(RULES, headers=ctx["headers"], json=sub_payload(ctx, **overrides))

    # REC-07: subscriptions/bills only as expenses.
    res = await post(type="income", category_id=income_cat, currency="MXN")
    assert res.status_code == 422
    # REC-08: an income must stay in the account currency (TAR-10).
    res = await post(kind="generic", type="income", category_id=income_cat)
    assert res.status_code == 422
    # REC-11: bills in the account currency; only bills may omit the amount.
    assert (await post(kind="bill", amount=None)).status_code == 422
    assert (await post(kind="bill", amount=None, currency="MXN")).status_code == 201
    assert (await post(amount=None)).status_code == 422
    # REC-10: only subscriptions have a trial.
    assert (await post(kind="generic", is_trial=True)).status_code == 422
    # REC-12: at most 3 offsets, each 0..30.
    assert (await post(reminder_days=[31])).status_code == 422
    assert (await post(reminder_days=[1, 2, 3, 4])).status_code == 422


# --- REC-10: trials ---------------------------------------------------------


async def test_rec10_trial_reminder_and_cancel_before_charge(client, db_session):
    """Caso 20: prueba con fin el 28 ⇒ aviso el 27 (in_app + desktop); al
    cancelarla el 27 se cancela el aviso y el 28 no hay cobro."""
    with freeze_time("2026-07-21 18:00:00"):
        ctx = await bootstrap_space(client)
        rule = await create_rule(
            client, ctx, is_trial=True, start_date="2026-07-28", currency="MXN", amount="99.00"
        )
        assert rule["status"] == "trial"
        assert rule["next_date"] == "2026-07-28"
        reminders = await reminders_of(db_session, rule["id"])
        assert {(r.kind, r.channel, r.fire_at, r.ref_date) for r in reminders} == {
            (ReminderKind.trial_ending, ch, date(2026, 7, 27), date(2026, 7, 28))
            for ch in (ReminderChannel.in_app, ReminderChannel.desktop)
        }
        assert "prueba" in reminders[0].message

    with freeze_time("2026-07-27 18:00:00"):
        res = await client.post(f"{RULES}/{rule['id']}/cancel", headers=ctx["headers"])
        assert res.status_code == 200
        assert res.json()["status"] == "canceled"
        assert res.json()["canceled_at"] == "2026-07-27"
        reminders = await reminders_of(db_session, rule["id"])
        assert {r.status for r in reminders} == {ReminderStatus.canceled}

    with freeze_time("2026-07-28 18:00:00"):
        assert await generate(client, ctx) == 0
        # REC-09: history is kept and the rule is still listed when asked for.
        res = await client.get(f"{RULES}?include_inactive=true", headers=ctx["headers"])
        assert [r["status"] for r in res.json()] == ["canceled"]


async def test_rec10_trial_converts_automatically(client, db_session):
    with freeze_time("2026-07-21 18:00:00"):
        ctx = await bootstrap_space(client)
        rule = await create_rule(
            client, ctx, is_trial=True, start_date="2026-07-28", currency="MXN", amount="99.00"
        )
    with freeze_time("2026-07-28 18:00:00"):
        assert await generate(client, ctx) == 1
        res = await client.get(RULES, headers=ctx["headers"])
        [listed] = [r for r in res.json() if r["id"] == rule["id"]]
        assert listed["status"] == "active"
        # Later charges use the regular notice (default 3 days before).
        reminders = await reminders_of(db_session, rule["id"])
        assert any(
            r.kind == ReminderKind.subscription_charge
            and r.ref_date == date(2026, 8, 28)
            and r.fire_at == date(2026, 8, 25)
            for r in reminders
        )


async def test_rec09_reactivate_restores_reminders(client, db_session):
    with freeze_time("2026-07-10 18:00:00"):
        ctx = await bootstrap_space(client)
        rule = await create_rule(client, ctx, currency="MXN", start_date="2026-07-20")
        pending = [r for r in await reminders_of(db_session, rule["id"])]
        assert {(r.kind, r.fire_at) for r in pending} == {
            (ReminderKind.subscription_charge, date(2026, 7, 17))
        }
        await client.post(f"{RULES}/{rule['id']}/cancel", headers=ctx["headers"])
        res = await client.post(f"{RULES}/{rule['id']}/reactivate", headers=ctx["headers"])
        assert res.json()["status"] == "active"
        statuses = {r.status for r in await reminders_of(db_session, rule["id"])}
        assert statuses == {ReminderStatus.pending}


async def test_rec12_editing_reminder_days_reschedules(client, db_session):
    with freeze_time("2026-07-10 18:00:00"):
        ctx = await bootstrap_space(client)
        rule = await create_rule(client, ctx, currency="MXN", start_date="2026-07-20")
        res = await client.patch(
            f"{RULES}/{rule['id']}", headers=ctx["headers"], json={"reminder_days": [5, 1]}
        )
        assert res.status_code == 200
        live = {
            (r.offset_days, r.fire_at)
            for r in await reminders_of(db_session, rule["id"])
            if r.status == ReminderStatus.pending
        }
        assert live == {(5, date(2026, 7, 15)), (1, date(2026, 7, 19))}


# --- REC-11: variable bills -------------------------------------------------


def bill_payload(ctx, **overrides):
    values = {
        "kind": "bill",
        "amount": None,
        "currency": "MXN",
        "description": "Luz",
        "start_date": "2026-06-05",
    }
    return sub_payload(ctx, **{**values, **overrides})


async def test_rec11_bills_are_captured_not_generated(client, db_session):
    """Caso 20: un servicio variable no genera transacciones; aparece en "Por
    capturar", se captura una vez (409 la segunda) y se puede omitir."""
    with freeze_time("2026-07-10 18:00:00"):
        ctx = await bootstrap_space(client)
        res = await client.post(RULES, headers=ctx["headers"], json=bill_payload(ctx))
        assert res.status_code == 201, res.text
        rule = res.json()
        assert rule["reminder_days"] == [0]

        assert await generate(client, ctx) == 0
        assert await rule_txns(client, ctx, rule["id"]) == []

        res = await client.get(f"{RULES}/pending-bills", headers=ctx["headers"])
        assert [b["scheduled_date"] for b in res.json()] == ["2026-06-05", "2026-07-05"]

        url = f"{RULES}/{rule['id']}"
        res = await client.post(
            f"{url}/capture",
            headers=ctx["headers"],
            json={"scheduled_date": "2026-07-05", "amount": "450.00", "date": "2026-07-08"},
        )
        assert res.status_code == 201, res.text
        txn = res.json()
        assert txn["date"] == "2026-07-08"
        assert Decimal(txn["amount"]) == Decimal("450.00")
        assert txn["needs_review"] is False

        res = await client.post(
            f"{url}/capture",
            headers=ctx["headers"],
            json={"scheduled_date": "2026-07-05", "amount": "450.00"},
        )
        assert res.status_code == 409
        # Not a real occurrence of the bill.
        res = await client.post(
            f"{url}/capture",
            headers=ctx["headers"],
            json={"scheduled_date": "2026-07-06", "amount": "450.00"},
        )
        assert res.status_code == 422

        res = await client.post(
            f"{url}/skip", headers=ctx["headers"], json={"scheduled_date": "2026-06-05"}
        )
        assert res.status_code == 204
        res = await client.get(f"{RULES}/pending-bills", headers=ctx["headers"])
        assert res.json() == []


async def test_rec12_bill_reminder_canceled_when_captured(client, db_session):
    with freeze_time("2026-07-10 18:00:00"):
        ctx = await bootstrap_space(client)
        res = await client.post(
            RULES, headers=ctx["headers"], json=bill_payload(ctx, amount="400.00")
        )
        rule = res.json()
        reminders = await reminders_of(db_session, rule["id"])
        assert {(r.kind, r.fire_at, r.status) for r in reminders} == {
            (ReminderKind.bill_due, date(2026, 8, 5), ReminderStatus.pending)
        }
        assert "aprox." in reminders[0].message

        # The bill arrived early: capturing it cancels its notice.
        res = await client.post(
            f"{RULES}/{rule['id']}/capture",
            headers=ctx["headers"],
            json={"scheduled_date": "2026-08-05", "amount": "390.00", "date": "2026-07-10"},
        )
        assert res.status_code == 201
        reminders = await reminders_of(db_session, rule["id"])
        assert {r.status for r in reminders} == {ReminderStatus.canceled}


# --- REC-06b / REC-13 -------------------------------------------------------


@freeze_time("2026-05-20 18:00:00")
async def test_rec06b_bimonthly(client):
    ctx = await bootstrap_space(client)
    rule = await create_rule(
        client,
        ctx,
        kind="generic",
        currency="MXN",
        amount="800.00",
        frequency="bimonthly",
        start_date="2026-01-31",
    )
    # Every 2 months from January; the May 31 charge has not arrived yet.
    assert await generate(client, ctx) == 2
    dates = sorted(t["date"] for t in await rule_txns(client, ctx, rule["id"]))
    assert dates == ["2026-01-31", "2026-03-31"]
    assert rule["next_date"] == "2026-05-31"


async def test_rec13_monthly_summary(client, db_session):
    with freeze_time("2026-07-21 18:00:00"):
        ctx = await bootstrap_space(client)
        await add_rate(db_session, date(2026, 7, 21), "18.50")
        await create_rule(client, ctx, description="Spotify", amount="129.00", currency="MXN")
        await create_rule(client, ctx)  # Claude, 20 USD
        await create_rule(
            client,
            ctx,
            description="Dominio",
            amount="1200.00",
            currency="MXN",
            frequency="yearly",
        )
        trial = await create_rule(
            client,
            ctx,
            description="Netflix",
            amount="300.00",
            currency="MXN",
            is_trial=True,
            start_date="2026-07-28",
        )
        canceled = await create_rule(client, ctx, description="Gym", amount="500", currency="MXN")
        await client.post(f"{RULES}/{canceled['id']}/cancel", headers=ctx["headers"])
        assert trial["status"] == "trial"

        res = await client.get(f"{RULES}/summary", headers=ctx["headers"])
        body = res.json()
        # 129 + 20×18.50 + 1200/12 + 300 (trial) = 899.00
        assert Decimal(body["monthly_total"]) == Decimal("899.00")
        assert Decimal(body["yearly_total"]) == Decimal("10788.00")
        assert body["is_approximate"] is True
        assert (body["active_count"], body["trial_count"], body["canceled_count"]) == (3, 1, 1)


# --- REM-08: desktop notifications -----------------------------------------


async def test_rem08_desktop_fires_after_hour_only(client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_notify(message: str, title: str = "Finanzas") -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(desktop, "notify", fake_notify)
    monkeypatch.setattr(desktop, "is_available", lambda: True)
    monkeypatch.setattr(settings, "desktop_notifications", True)

    with freeze_time("2026-07-17 06:00:00"):
        ctx = await bootstrap_space(client)
        await create_rule(client, ctx, currency="MXN", amount="129.00", start_date="2026-07-20")
    space = await db_session.get(Space, uuid.UUID(ctx["space_id"]))
    assert space is not None

    with freeze_time("2026-07-17 14:00:00"):  # 08:00 CDMX: too early
        assert await fire_desktop_reminders(db_session, space, date(2026, 7, 17)) == 0
    with freeze_time("2026-07-17 16:00:00"):  # 10:00 CDMX
        assert await fire_desktop_reminders(db_session, space, date(2026, 7, 17)) == 1
        assert await fire_desktop_reminders(db_session, space, date(2026, 7, 17)) == 0
    assert sent == ["Claude se cobra el 20 jul: $129.00 MXN en Débito."]


async def test_rem08_desktop_disabled_cancels(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "desktop_notifications", False)
    with freeze_time("2026-07-17 16:00:00"):
        ctx = await bootstrap_space(client)
        rule = await create_rule(client, ctx, currency="MXN", start_date="2026-07-20")
        space = await db_session.get(Space, uuid.UUID(ctx["space_id"]))
        assert space is not None
        assert await fire_desktop_reminders(db_session, space, date(2026, 7, 17)) == 0
        by_channel = {r.channel: r.status for r in await reminders_of(db_session, rule["id"])}
        assert by_channel[ReminderChannel.desktop] == ReminderStatus.canceled
        assert by_channel[ReminderChannel.in_app] == ReminderStatus.pending


# --- GLO-05 / ESP-03 --------------------------------------------------------


async def test_subscription_permissions(client):
    owner = await bootstrap_space(client)
    shared = await client.post("/api/v1/spaces", headers=owner["headers"], json={"name": "Casa"})
    space_id = shared.json()["id"]
    viewer = await add_member(client, owner["headers"], space_id, "viewer", "viewer@example.com")
    fake = uuid.uuid4()
    assert (await client.get(f"{RULES}/pending-bills", headers=viewer)).status_code == 200
    assert (await client.get(f"{RULES}/summary", headers=viewer)).status_code == 200
    for path, body in (
        (f"{RULES}/{fake}/cancel", None),
        (f"{RULES}/{fake}/reactivate", None),
        (f"{RULES}/{fake}/capture", {"scheduled_date": "2026-07-05", "amount": "1.00"}),
        (f"{RULES}/{fake}/skip", {"scheduled_date": "2026-07-05"}),
    ):
        assert (await client.post(path, headers=viewer, json=body)).status_code == 403

    stranger = await bootstrap_space(client)
    headers = {**stranger["headers"], "X-Space-Id": space_id}
    assert (await client.get(f"{RULES}/pending-bills", headers=headers)).status_code == 404


# --- PRO-04 -------------------------------------------------------------------


@freeze_time("2026-07-10 18:00:00")
async def test_pro04_bills_projected_only_with_estimate(client):
    from tests.test_forecast import forecast

    ctx = await bootstrap_space(client)
    await client.post(RULES, headers=ctx["headers"], json=bill_payload(ctx))
    await client.post(
        RULES,
        headers=ctx["headers"],
        json=bill_payload(ctx, description="Agua", amount="250.00"),
    )
    body = await forecast(client, ctx, horizon_months=2, cash_adjustment="0")
    descriptions = {e["description"] for e in body["events"]}
    assert "Luz" not in descriptions
    water = [e for e in body["events"] if e["description"] == "Agua"]
    assert water and all(e["is_estimate"] for e in water)


@freeze_time("2026-07-21 18:00:00")
async def test_cancel_url_only_http(client):
    """XSS: the cancel link is rendered as href, so only http(s) is accepted."""
    ctx = await bootstrap_space(client)
    bad = await client.post(
        RULES,
        headers=ctx["headers"],
        json=sub_payload(ctx, currency="MXN", cancel_url="javascript:alert(1)"),
    )
    assert bad.status_code == 422
    rule = await create_rule(client, ctx, currency="MXN", cancel_url="https://claude.ai/billing")
    res = await client.patch(
        f"{RULES}/{rule['id']}", headers=ctx["headers"], json={"cancel_url": "data:text/html,x"}
    )
    assert res.status_code == 422


@freeze_time("2026-07-10 18:00:00")
async def test_rec11_capture_rejects_far_future_dates(client):
    """Bounded work: a far-future scheduled_date is rejected up front."""
    ctx = await bootstrap_space(client)
    res = await client.post(RULES, headers=ctx["headers"], json=bill_payload(ctx))
    url = f"{RULES}/{res.json()['id']}"
    for path, body in (
        ("capture", {"scheduled_date": "9999-12-05", "amount": "1.00"}),
        ("skip", {"scheduled_date": "9999-12-05"}),
    ):
        assert (
            await client.post(f"{url}/{path}", headers=ctx["headers"], json=body)
        ).status_code == 422
