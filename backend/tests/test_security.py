"""Tests de regresión de la auditoría de seguridad.

Cubren GLO-05 (aislamiento por espacio en rutas que antes no revalidaban
referencias), CWE-1236 (CSV formula injection en el export), CWE-693
(cabeceras de seguridad) y CWE-613 (claims obligatorios del JWT).
"""

import uuid

import jwt as pyjwt
from freezegun import freeze_time

from tests.conftest import JWT_SECRET, auth_headers, bootstrap_space
from tests.test_cards import create_card


async def other_space_ctx(client):
    """Un segundo espacio, de otro usuario, sin relación con el primero."""
    return await bootstrap_space(client, uuid.uuid4())


# --- GLO-05: referencias cruzadas entre espacios ---------------------------


@freeze_time("2026-06-15 18:00:00")
async def test_glo05_msi_backfill_rejects_foreign_category(client):
    """El backfill MSI valida card_id contra el espacio; category_id también."""
    ctx = await bootstrap_space(client)
    intruder = await other_space_ctx(client)
    card = await create_card(client, ctx)

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
            # Categoría válida, pero de OTRO espacio.
            "category_id": intruder["expense_categories"]["Otros"]["id"],
            "current_is_charged": True,
        },
    )
    assert res.status_code == 404, res.text


async def test_glo05_msi_backfill_rejects_income_category(client):
    """TXN-01: un plan MSI es un gasto; no acepta categoría de ingreso."""
    ctx = await bootstrap_space(client)
    card = await create_card(client, ctx)

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
            "category_id": ctx["income_categories"]["Nómina"]["id"],
            "current_is_charged": True,
        },
    )
    assert res.status_code == 422, res.text


async def test_glo05_recurring_update_rejects_foreign_references(client):
    """REC-04: el PATCH no puede reapuntar la regla a catálogos de otro espacio."""
    ctx = await bootstrap_space(client)
    intruder = await other_space_ctx(client)

    created = await client.post(
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
            "start_date": "2026-01-15",
            "month_day": 15,
        },
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    foreign_category = intruder["expense_categories"]["Comida"]["id"]
    res = await client.patch(
        f"/api/v1/recurring-rules/{rule_id}",
        headers=ctx["headers"],
        json={"category_id": foreign_category},
    )
    assert res.status_code == 404, res.text

    foreign_method = intruder["methods"]["Efectivo"]["id"]
    res = await client.patch(
        f"/api/v1/recurring-rules/{rule_id}",
        headers=ctx["headers"],
        json={"payment_method_id": foreign_method},
    )
    assert res.status_code == 404, res.text

    # La regla quedó intacta tras los intentos fallidos.
    current = await client.get("/api/v1/recurring-rules", headers=ctx["headers"])
    rule = next(r for r in current.json() if r["id"] == rule_id)
    assert rule["category_id"] == ctx["categories"]["Entretenimiento"]["id"]
    assert rule["payment_method_id"] == ctx["methods"]["Débito"]["id"]


# --- CWE-1236: CSV formula injection --------------------------------------


async def test_csv_export_neutralizes_formulas(client):
    """IMP-07: una descripción con `=` no debe exportarse como fórmula viva."""
    ctx = await bootstrap_space(client)
    payload = {
        "type": "expense",
        "date": "2026-06-01",
        "amount": "150.00",
        "currency": "MXN",
        "category_id": ctx["expense_categories"]["Comida"]["id"],
        "payment_method_id": ctx["methods"]["Efectivo"]["id"],
        "description": '=HYPERLINK("http://evil.example","x")',
        "notes": "@SUM(A1:A9)",
    }
    res = await client.post("/api/v1/transactions", headers=ctx["headers"], json=payload)
    assert res.status_code == 201, res.text

    res = await client.get("/api/v1/exports/transactions.csv", headers=ctx["headers"])
    assert res.status_code == 200, res.text
    body = res.text
    assert "'=HYPERLINK" in body
    assert "'@SUM(A1:A9)" in body
    # Ninguna celda arranca con un carácter que Excel interprete como fórmula.
    for line in body.splitlines()[1:]:
        for cell in line.split(","):
            assert not cell.strip('"').startswith(("=", "+", "@"))


# --- CWE-693: cabeceras de seguridad --------------------------------------


async def test_security_headers_present(client):
    res = await client.get("/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "no-referrer"
    assert res.headers["Cache-Control"] == "no-store"
    # env=dev: sin HSTS (en local se sirve por HTTP).
    assert "Strict-Transport-Security" not in res.headers


# --- CWE-613: claims obligatorios del JWT ---------------------------------


async def test_jwt_without_exp_is_rejected(client):
    """Un token sin exp no puede tratarse como válido para siempre."""
    token = pyjwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "email": "user@example.com",
            "user_metadata": {},
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    res = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


async def test_valid_token_still_accepted(client):
    res = await client.get("/api/v1/me", headers=auth_headers())
    assert res.status_code == 200
