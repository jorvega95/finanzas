"""Fase 4 tests: INV-01..INV-06, PAT-01."""

from datetime import date
from decimal import Decimal

from freezegun import freeze_time

from app.models.fx import ExchangeRate
from app.services import prices
from tests.conftest import bootstrap_space
from tests.test_cards import charge, close_cycles, create_card


class FakeProvider:
    """PriceProvider de prueba: cuenta llamadas y puede fallar."""

    def __init__(self, quotes=None, fail=False):
        self.quotes = {k: Decimal(v) for k, v in (quotes or {}).items()}
        self.fail = fail
        self.calls = 0

    async def get_quotes(self, symbols):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        return {s: self.quotes[s] for s in symbols if s in self.quotes}


async def make_account(client, ctx, kind="crypto", name="Binance"):
    res = await client.post(
        "/api/v1/investments/accounts",
        headers=ctx["headers"],
        json={"name": name, "kind": kind},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def move(client, ctx, account_id, expected=201, **body):
    payload = {
        "type": "buy",
        "asset_symbol": "bitcoin",
        "quantity": "0.5",
        "price": "100.00",
        "date": "2026-06-01",
        **body,
    }
    res = await client.post(
        f"/api/v1/investments/accounts/{account_id}/movements",
        headers=ctx["headers"],
        json=payload,
    )
    assert res.status_code == expected, res.text
    return res.json()


@freeze_time("2026-06-20 18:00:00")
async def test_inv02_weighted_average_and_sell_pnl(client, db_session, monkeypatch):
    """INV-02: avg ponderado en buy; sell baja qty, avg intacto, P&L realizado."""
    monkeypatch.setattr(prices, "_default_provider", FakeProvider({"bitcoin": "150"}))
    ctx = await bootstrap_space(client)
    db_session.add(ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 20), rate=Decimal("1")))
    await db_session.commit()
    account = await make_account(client, ctx)

    # buy 1 @ 100, buy 1 @ 200 ⇒ avg 150.
    await move(client, ctx, account["id"], quantity="1", price="100.00")
    body = await move(client, ctx, account["id"], quantity="1", price="200.00")
    holding = body["holdings"][0]
    assert Decimal(holding["quantity"]) == Decimal("2")
    assert Decimal(holding["avg_cost"]) == Decimal("150")

    # sell 0.5 @ 180 ⇒ realized = 0.5 × (180 − 150) = 15; avg NO cambia.
    body = await move(client, ctx, account["id"], type="sell", quantity="0.5", price="180.00")
    holding = body["holdings"][0]
    assert Decimal(holding["quantity"]) == Decimal("1.5")
    assert Decimal(holding["avg_cost"]) == Decimal("150")
    assert Decimal(holding["realized_pnl"]) == Decimal("15.00")
    assert Decimal(body["total_realized_pnl"]) == Decimal("15.00")

    # sell con qty > posición ⇒ 422 (INV-02).
    await move(client, ctx, account["id"], type="sell", quantity="99", price="180.00", expected=422)
    # withdraw reduce sin P&L; deposit suma.
    await move(client, ctx, account["id"], type="withdraw", quantity="0.5", price=None)
    body = await move(client, ctx, account["id"], type="deposit", quantity="1", price=None)
    holding = body["holdings"][0]
    assert Decimal(holding["quantity"]) == Decimal("2")
    assert Decimal(holding["avg_cost"]) == Decimal("150")  # deposit sin precio no toca avg


@freeze_time("2026-06-20 18:00:00")
async def test_inv01_crypto_decimals_preserved(client, db_session, monkeypatch):
    monkeypatch.setattr(prices, "_default_provider", FakeProvider({"bitcoin": "100"}))
    ctx = await bootstrap_space(client)
    account = await make_account(client, ctx)
    body = await move(client, ctx, account["id"], quantity="0.1234567891", price="100.00")
    assert body["holdings"][0]["quantity"] == "0.1234567891"  # NUMERIC(28,10)


@freeze_time("2026-06-20 18:00:00")
async def test_inv03_cache_ttl_and_fallback(client, db_session, monkeypatch):
    """INV-03: 1 batch por refresh; dentro del TTL no se re-llama; si el
    proveedor falla se sirve el último precio cacheado."""
    provider = FakeProvider({"bitcoin": "50000"})
    monkeypatch.setattr(prices, "_default_provider", provider)
    ctx = await bootstrap_space(client)
    db_session.add(
        ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 20), rate=Decimal("18"))
    )
    await db_session.commit()
    account = await make_account(client, ctx)
    await move(client, ctx, account["id"], quantity="1", price="40000.00")

    res = await client.get("/api/v1/investments/portfolio", headers=ctx["headers"])
    first_calls = provider.calls
    assert first_calls >= 1
    # Segunda consulta dentro del TTL: cero llamadas nuevas (caché).
    res = await client.get("/api/v1/investments/portfolio", headers=ctx["headers"])
    assert provider.calls == first_calls
    assert res.json()["holdings"][0]["price"] == "50000.00000000"

    # Proveedor caído tras expirar el TTL ⇒ sirve caché con fetched_at.
    provider.fail = True
    with freeze_time("2026-06-20 19:00:00"):
        res = await client.get("/api/v1/investments/portfolio", headers=ctx["headers"])
    holding = res.json()["holdings"][0]
    assert holding["price"] == "50000.00000000"
    assert holding["price_fetched_at"] is not None


@freeze_time("2026-06-20 18:00:00")
async def test_inv04_manual_price_and_inv06_valuation_fx04(client, db_session, monkeypatch):
    """INV-04: precio manual (CETES en MXN); INV-06/FX-04: valuación con la
    tasa del día, no congelada."""
    monkeypatch.setattr(prices, "_default_provider", FakeProvider({}))
    ctx = await bootstrap_space(client)
    db_session.add_all(
        [
            ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 1), rate=Decimal("17")),
            ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 20), rate=Decimal("20")),
        ]
    )
    await db_session.commit()

    account = await make_account(client, ctx, kind="fixed_income", name="CETES")
    await move(
        client,
        ctx,
        account["id"],
        asset_symbol="CETES-28",
        quantity="100",
        price="9.85",
        currency="MXN",
    )
    res = await client.post(
        "/api/v1/investments/prices",
        headers=ctx["headers"],
        json={"symbol": "CETES-28", "price": "10.00", "currency": "MXN"},
    )
    assert res.status_code == 200

    res = await client.get("/api/v1/investments/portfolio", headers=ctx["headers"])
    holding = res.json()["holdings"][0]
    assert holding["price_source"] == "manual"
    assert Decimal(holding["value_base"]) == Decimal("1000.00")  # 100 × 10 MXN
    assert Decimal(holding["unrealized_pnl"]) == Decimal("15.00")  # 100 × (10 − 9.85)

    # FX-04: un holding USD se valúa con la tasa de HOY (20), no la de junio 1.
    usd_account = await make_account(client, ctx, kind="crypto", name="Wallet")
    monkeypatch.setattr(prices, "_default_provider", FakeProvider({"ethereum": "1000"}))
    await move(
        client, ctx, usd_account["id"], asset_symbol="ethereum", quantity="1", price="900.00"
    )
    res = await client.get("/api/v1/investments/portfolio", headers=ctx["headers"])
    eth = next(h for h in res.json()["holdings"] if h["asset_symbol"] == "ethereum")
    assert Decimal(eth["value_base"]) == Decimal("20000.00")  # 1 × 1000 USD × 20 (hoy)


@freeze_time("2026-06-20 18:00:00")
async def test_inv05_snapshot_idempotent_and_history_frozen(client, db_session, monkeypatch):
    """INV-05: un snapshot por día; el histórico nunca se reconstruye con
    precios actuales."""
    provider = FakeProvider({"bitcoin": "100"})
    monkeypatch.setattr(prices, "_default_provider", provider)
    ctx = await bootstrap_space(client)
    db_session.add(ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 20), rate=Decimal("1")))
    await db_session.commit()
    account = await make_account(client, ctx)
    await move(client, ctx, account["id"], quantity="2", price="90.00")

    res = await client.post("/api/v1/investments/snapshot", headers=ctx["headers"])
    assert res.json()["total_value"] == "200.00"  # 2 × 100
    res = await client.post("/api/v1/investments/snapshot", headers=ctx["headers"])
    snapshots = (await client.get("/api/v1/investments/snapshots", headers=ctx["headers"])).json()
    assert len(snapshots) == 1  # idempotente

    # Al día siguiente el precio cambia: el snapshot de ayer queda intacto.
    provider.quotes["bitcoin"] = Decimal("500")
    with freeze_time("2026-06-21 18:00:00"):
        db_session.add(
            ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 21), rate=Decimal("1"))
        )
        await db_session.commit()
        await client.post("/api/v1/investments/snapshot", headers=ctx["headers"])
        snapshots = (
            await client.get("/api/v1/investments/snapshots", headers=ctx["headers"])
        ).json()
    assert [s["total_value"] for s in snapshots] == ["200.00", "1000.00"]


@freeze_time("2026-06-20 18:00:00")
async def test_pat01_net_worth_assets_minus_card_debt(client, db_session, monkeypatch):
    """PAT-01: patrimonio = portafolio − deuda TDC (a+b+c)."""
    monkeypatch.setattr(prices, "_default_provider", FakeProvider({"bitcoin": "100"}))
    ctx = await bootstrap_space(client)
    db_session.add(ExchangeRate(base="USD", quote="MXN", date=date(2026, 6, 20), rate=Decimal("1")))
    await db_session.commit()

    # Activos: 3 BTC × 100 = 300.
    account = await make_account(client, ctx)
    await move(client, ctx, account["id"], quantity="3", price="100.00")
    await client.post("/api/v1/investments/snapshot", headers=ctx["headers"])

    # Pasivos: statement cerrado 500 + ciclo en curso 200 = 700.
    card = await create_card(client, ctx)
    await charge(client, ctx, card["payment_method_id"], "2026-06-10", "500.00")
    await charge(client, ctx, card["payment_method_id"], "2026-06-18", "200.00")
    await close_cycles(client, ctx)

    res = await client.post("/api/v1/investments/net-worth/snapshot", headers=ctx["headers"])
    body = res.json()
    assert body["assets"] == "300.00"
    assert body["liabilities"] == "700.00"
    assert body["net_worth"] == "-400.00"

    # Idempotente por día.
    await client.post("/api/v1/investments/net-worth/snapshot", headers=ctx["headers"])
    history = (await client.get("/api/v1/investments/net-worth", headers=ctx["headers"])).json()
    assert len(history) == 1
