"""TDC-05a: cycle_hint overrides cutoff_day_policy when date == cutoff day."""

from freezegun import freeze_time

from tests.conftest import bootstrap_space


def credit_payload(ctx, statement_day=3, cutoff_day_policy="include", last4="5500", **overrides):
    return {
        "card_type_id": ctx["card_type_by_behavior"]["credit"]["id"],
        "alias": "Test Ciclo",
        "bank": "Test",
        "network": "Visa",
        "last4": last4,
        "statement_day": statement_day,
        "payment_due_days": 20,
        "cutoff_day_policy": cutoff_day_policy,
        **overrides,
    }


async def create_card(client, ctx, **overrides):
    res = await client.post(
        "/api/v1/cards", headers=ctx["headers"], json=credit_payload(ctx, **overrides)
    )
    assert res.status_code == 201, res.text
    return res.json()


async def charge(client, ctx, method_id, date, amount, cycle_hint=None):
    body = {
        "type": "expense",
        "date": date,
        "amount": amount,
        "currency": "MXN",
        "category_id": ctx["categories"]["Comida"]["id"],
        "payment_method_id": method_id,
    }
    if cycle_hint is not None:
        body["cycle_hint"] = cycle_hint
    res = await client.post("/api/v1/transactions", headers=ctx["headers"], json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def close_cycles(client, ctx):
    res = await client.post("/api/v1/cards/close-cycles", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    return res.json()


@freeze_time("2026-06-04 18:00:00")
async def test_tdc05a_hint_next_overrides_include_policy(client):
    """TDC-05a: cycle_hint='next' sends a cutoff-day charge to the next cycle,
    overriding the card's include policy."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx, statement_day=3, cutoff_day_policy="include")
    method = card["payment_method_id"]

    # No hint + include: Jun 3 charge → cycle ending Jun 3.
    await charge(client, ctx, method, "2026-06-03", "100.00")
    # hint=next: same date → cycle ending Jul 3 (open).
    await charge(client, ctx, method, "2026-06-03", "200.00", cycle_hint="next")

    closed = await close_cycles(client, ctx)
    jun3_st = next(s for s in closed if s["period_end"] == "2026-06-03")
    assert jun3_st["computed_total"] == "100.00"

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "200.00"


@freeze_time("2026-06-04 18:00:00")
async def test_tdc05a_hint_current_overrides_next_cycle_policy(client):
    """TDC-05a: cycle_hint='current' sends a cutoff-day charge to the current cycle,
    overriding the card's next_cycle policy."""
    ctx = await bootstrap_space(client)
    card = await create_card(
        client, ctx, statement_day=3, cutoff_day_policy="next_cycle", last4="5501"
    )
    method = card["payment_method_id"]

    # No hint + next_cycle: Jun 3 charge → cycle ending Jul 3 (open).
    await charge(client, ctx, method, "2026-06-03", "100.00")
    # hint=current: same date → cycle ending Jun 3 (closes today).
    await charge(client, ctx, method, "2026-06-03", "200.00", cycle_hint="current")

    closed = await close_cycles(client, ctx)
    jun3_st = next(s for s in closed if s["period_end"] == "2026-06-03")
    assert jun3_st["computed_total"] == "200.00"

    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "100.00"


@freeze_time("2026-06-04 18:00:00")
async def test_tdc05a_hint_ignored_on_non_cutoff_day(client):
    """TDC-05a: cycle_hint is silently ignored when date != cutoff day."""
    ctx = await bootstrap_space(client)
    card = await create_card(
        client, ctx, statement_day=3, cutoff_day_policy="include", last4="5502"
    )
    method = card["payment_method_id"]

    # Jun 5 is not the cutoff day (next cutoff = Jul 3). hint has no effect.
    await charge(client, ctx, method, "2026-06-05", "150.00", cycle_hint="current")

    # Nothing to close on Jun 4: Jun 3 statement doesn't exist, Jul 3 not past.
    closed = await close_cycles(client, ctx)
    assert not any(s["period_end"] == "2026-06-03" for s in closed)

    # Charge is in the open Jul 3 cycle.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "150.00"


@freeze_time("2026-06-04 18:00:00")
async def test_tdc05a_edit_with_cycle_hint_moves_charge(client):
    """TDC-05a: editing a cutoff-day charge with cycle_hint reassigns it and
    recomputes both statement totals."""
    ctx = await bootstrap_space(client)
    card = await create_card(
        client, ctx, statement_day=3, cutoff_day_policy="include", last4="5503"
    )
    method = card["payment_method_id"]

    # Create on Jun 3 without hint → Jun 3 cycle (include).
    txn = await charge(client, ctx, method, "2026-06-03", "300.00")
    closed = await close_cycles(client, ctx)
    jun3_st = next(s for s in closed if s["period_end"] == "2026-06-03")
    assert jun3_st["computed_total"] == "300.00"

    # Edit with cycle_hint='next': charge moves from Jun 3 to Jul 3 cycle.
    res = await client.put(
        f"/api/v1/transactions/{txn['id']}",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-03",
            "amount": "300.00",
            "currency": "MXN",
            "category_id": ctx["categories"]["Comida"]["id"],
            "payment_method_id": method,
            "cycle_hint": "next",
        },
    )
    assert res.status_code == 200, res.text

    # Jun 3 statement total recomputed to 0 (charge removed).
    statements = (
        await client.get(f"/api/v1/cards/{card['id']}/statements", headers=ctx["headers"])
    ).json()
    updated_jun3 = next(s for s in statements if s["period_end"] == "2026-06-03")
    assert updated_jun3["computed_total"] == "0.00"

    # Charge is now in the open Jul 3 cycle.
    detail = (await client.get(f"/api/v1/cards/{card['id']}", headers=ctx["headers"])).json()
    assert detail["debt"]["current_cycle_spend"] == "300.00"
