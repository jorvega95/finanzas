"""FAC-09: invoicing and declaration reminders."""

import datetime as dt
import uuid

import pytest
from freezegun import freeze_time
from sqlalchemy import select

from app.core.config import settings
from app.models.reminders import Reminder, ReminderKind, ReminderStatus
from app.models.spaces import Space
from app.services.billing_reminders import period_ref, sync_reminders
from app.services.reminders import fire_due_reminders
from tests.test_billing import payments, save_invoice, setup, usd_income
from tests.test_tax_filings import setup as setup_rfc3
from tests.test_wallets import post_txn


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "files_dir", str(tmp_path / "files"))


async def reminders(db_session, kind):
    db_session.expire_all()
    rows = await db_session.scalars(select(Reminder).where(Reminder.kind == kind))
    return sorted(rows.all(), key=lambda r: (r.fire_at, r.channel))


def summary(rows):
    return [(r.fire_at.isoformat(), r.channel.value, r.status.value) for r in rows]


async def resync(db_session, ctx):
    space = await db_session.get(Space, uuid.UUID(ctx["space_id"]))
    await sync_reminders(db_session, space)
    await db_session.commit()


@freeze_time("2026-10-02 10:00:00")
async def test_fac09_invoice_pending_scheduled_and_canceled(client, db_session):
    ctx, _ = await setup(client)
    await post_txn(client, ctx, **usd_income(ctx, day="2026-10-02"))
    rows = await reminders(db_session, ReminderKind.invoice_pending)
    assert summary(rows) == [
        ("2026-10-02", "desktop", "pending"),
        ("2026-10-02", "in_app", "pending"),
        ("2026-10-29", "desktop", "pending"),
        ("2026-10-29", "in_app", "pending"),
    ]
    assert "USD 325.00 del 2026-10-02 (Greenlight)" in rows[0].message

    # REM-02: syncing again creates nothing new.
    await resync(db_session, ctx)
    assert len(await reminders(db_session, ReminderKind.invoice_pending)) == 4

    # Invoiced ⇒ canceled (sent ones too, REM-01b); invoice removed ⇒ back.
    await fire_due_reminders(db_session, dt.date(2026, 10, 2))
    [payment] = await payments(client, ctx)
    await save_invoice(client, ctx, payment["id"])
    rows = await reminders(db_session, ReminderKind.invoice_pending)
    assert {r.status for r in rows} == {ReminderStatus.canceled}
    await client.delete(f"/api/v1/billing/payments/{payment['id']}/invoice", headers=ctx["headers"])
    rows = await reminders(db_session, ReminderKind.invoice_pending)
    assert {r.status for r in rows} == {ReminderStatus.pending}


@freeze_time("2026-10-02 10:00:00")
async def test_fac09_deleted_income_cancels_and_old_payments_dont_spam(client, db_session):
    ctx, greenlight = await setup(client)
    txn = await post_txn(client, ctx, **usd_income(ctx, day="2026-10-02"))
    await client.delete(f"/api/v1/transactions/{txn['id']}", headers=ctx["headers"])
    rows = await reminders(db_session, ReminderKind.invoice_pending)
    assert rows and {r.status for r in rows} == {ReminderStatus.canceled}
    # An old payment from a past month schedules nothing in the past.
    await client.post(
        "/api/v1/billing/payments",
        headers=ctx["headers"],
        json={"client_id": greenlight["id"], "payment_date": "2026-08-10", "amount": "5.00"},
    )
    pending = [
        r
        for r in await reminders(db_session, ReminderKind.invoice_pending)
        if r.status == "pending"
    ]
    assert pending == []


async def test_fac09_tax_filing_due_lifecycle(client, db_session):
    with freeze_time("2026-10-02 10:00:00"):
        ctx, _ = await setup_rfc3(client)  # RFC +3 days
        await post_txn(client, ctx, **usd_income(ctx, day="2026-10-02"))
        rows = await reminders(db_session, ReminderKind.tax_filing_due)
        # Deadline Nov 20 (17 + 3): day 1 (offset 0) and deadline − 3.
        assert [(r.fire_at.isoformat(), r.offset_days) for r in rows if r.channel == "in_app"] == [
            ("2026-11-01", 0),
            ("2026-11-17", 3),
        ]
        assert rows[0].ref_id == period_ref(uuid.UUID(ctx["space_id"]), dt.date(2026, 10, 1))
        assert rows[0].message == "Declara octubre 2026 (RESICO). Fecha límite 2026-11-20"

    with freeze_time("2026-11-05 10:00:00"):
        # Fire the day-1 notice, then declare with 59 to pay.
        await fire_due_reminders(db_session, dt.date(2026, 11, 5))
        res = await client.post(
            "/api/v1/billing/filings",
            headers=ctx["headers"],
            json={
                "period": "2026-10-01",
                "filed_date": "2026-11-05",
                "amount_due": "59.00",
                "valid_until": "2026-11-19",
            },
        )
        filing = res.json()
        rows = await reminders(db_session, ReminderKind.tax_filing_due)
        live = [r for r in rows if r.status != ReminderStatus.canceled]
        # The sent day-1 notice stays; the payment reminder follows "vigente hasta".
        assert ("2026-11-01", "in_app", "sent") in summary(live)
        upcoming = [r for r in live if r.status == ReminderStatus.pending and r.channel == "in_app"]
        assert [(r.fire_at.isoformat(), r.offset_days) for r in upcoming] == [("2026-11-16", 3)]
        assert upcoming[0].message.startswith("Paga la declaración de octubre 2026: $59.00")

        # Paid ⇒ every reminder of the period is canceled.
        await client.put(
            f"/api/v1/billing/filings/{filing['id']}/payment",
            headers=ctx["headers"],
            json={"paid_date": "2026-11-05", "paid_amount": "59.00"},
        )
        rows = await reminders(db_session, ReminderKind.tax_filing_due)
        assert {r.status for r in rows} == {ReminderStatus.canceled}
