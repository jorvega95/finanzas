"""Fase 1 tests: CAT-01, CAT-04..CAT-07, GLO-03, ESP-03 (viewer read-only)."""

import uuid

from app.models.spaces import SpaceMember, SpaceRole
from tests.conftest import auth_headers, bootstrap_space


async def test_cat03_update_expense_nature(client):
    """CAT-03: PATCH can change expense_nature on an existing expense category."""
    ctx = await bootstrap_space(client)
    cat_id = ctx["categories"]["Comida"]["id"]  # seeded as "variable"

    res = await client.patch(
        f"/api/v1/catalogs/categories/{cat_id}",
        headers=ctx["headers"],
        json={"expense_nature": "discretionary"},
    )
    assert res.status_code == 200
    assert res.json()["expense_nature"] == "discretionary"

    # Verify income category ignores expense_nature update.
    income_id = ctx["categories"]["Nómina"]["id"]
    res = await client.patch(
        f"/api/v1/catalogs/categories/{income_id}",
        headers=ctx["headers"],
        json={"expense_nature": "fixed"},
    )
    assert res.status_code == 200
    assert res.json()["expense_nature"] is None


async def test_cat03_expense_nature_explicit(client):
    """CAT-03: expense_nature is stored verbatim when explicitly provided."""
    ctx = await bootstrap_space(client)
    for nature in ("fixed", "variable", "discretionary"):
        res = await client.post(
            "/api/v1/catalogs/categories",
            headers=ctx["headers"],
            json={"name": f"Test {nature}", "kind": "expense", "expense_nature": nature},
        )
        assert res.status_code == 201, nature
        assert res.json()["expense_nature"] == nature, nature


async def test_cat03_expense_default_nature_is_variable(client):
    """CAT-03: omitting expense_nature on an expense category defaults to 'variable'."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=ctx["headers"],
        json={"name": "Sin naturaleza", "kind": "expense"},
    )
    assert res.status_code == 201
    assert res.json()["expense_nature"] == "variable"


async def test_cat03_income_nature_always_null(client):
    """CAT-03: income categories never carry expense_nature, even when sent."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=ctx["headers"],
        json={"name": "Bono", "kind": "income", "expense_nature": "fixed"},
    )
    assert res.status_code == 201
    assert res.json()["expense_nature"] is None


async def test_cat01_unique_name_accent_and_case_insensitive(client):
    """CAT-01: 'Comida' ya existe ⇒ 'comida', 'CÓMIDA' chocan (unaccent+lower)."""
    ctx = await bootstrap_space(client)
    for name in ["comida", "COMIDA", "Cómida"]:
        res = await client.post(
            "/api/v1/catalogs/categories",
            headers=ctx["headers"],
            json={"name": name, "kind": "expense"},
        )
        assert res.status_code == 409, name
    # Same name with different kind is fine (uniqueness is per space+kind).
    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=ctx["headers"],
        json={"name": "Comida", "kind": "income"},
    )
    assert res.status_code == 201

    # Payment methods: unique per space.
    res = await client.post(
        "/api/v1/catalogs/payment-methods",
        headers=ctx["headers"],
        json={"name": "efectívo", "type": "cash"},
    )
    assert res.status_code == 409


async def test_cat04_deactivation_hides_from_forms_but_keeps_it(client):
    ctx = await bootstrap_space(client)
    cat_id = ctx["categories"]["Regalos"]["id"]
    res = await client.patch(
        f"/api/v1/catalogs/categories/{cat_id}",
        headers=ctx["headers"],
        json={"is_active": False},
    )
    assert res.status_code == 200

    names = [
        c["name"]
        for c in (await client.get("/api/v1/catalogs/categories", headers=ctx["headers"])).json()
    ]
    assert "Regalos" not in names

    with_inactive = [
        c["name"]
        for c in (
            await client.get(
                "/api/v1/catalogs/categories?include_inactive=true", headers=ctx["headers"]
            )
        ).json()
    ]
    assert "Regalos" in with_inactive

    # CAT-04: reactivable at any time.
    res = await client.patch(
        f"/api/v1/catalogs/categories/{cat_id}",
        headers=ctx["headers"],
        json={"is_active": True},
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is True


async def test_cat05_cannot_deactivate_last_active(client):
    """CAT-05: ni la última categoría activa de un kind ni el último método."""
    ctx = await bootstrap_space(client)
    income = list(ctx["income_categories"].values())
    assert len(income) == 4
    for cat in income[:-1]:
        res = await client.patch(
            f"/api/v1/catalogs/categories/{cat['id']}",
            headers=ctx["headers"],
            json={"is_active": False},
        )
        assert res.status_code == 200
    res = await client.patch(
        f"/api/v1/catalogs/categories/{income[-1]['id']}",
        headers=ctx["headers"],
        json={"is_active": False},
    )
    assert res.status_code == 422

    methods = list(ctx["methods"].values())
    for m in methods[:-1]:
        res = await client.patch(
            f"/api/v1/catalogs/payment-methods/{m['id']}",
            headers=ctx["headers"],
            json={"is_active": False},
        )
        assert res.status_code == 200
    res = await client.patch(
        f"/api/v1/catalogs/payment-methods/{methods[-1]['id']}",
        headers=ctx["headers"],
        json={"is_active": False},
    )
    assert res.status_code == 422


async def test_cat06_subcategories_max_two_levels_and_inheritance(client):
    ctx = await bootstrap_space(client)
    parent_id = ctx["categories"]["Comida"]["id"]

    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=ctx["headers"],
        json={"name": "Restaurantes", "kind": "income", "parent_id": parent_id},
    )
    assert res.status_code == 201
    sub = res.json()
    # CAT-06: inherits kind and expense_nature from the parent.
    assert sub["kind"] == "expense"
    assert sub["expense_nature"] == ctx["categories"]["Comida"]["expense_nature"]

    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=ctx["headers"],
        json={"name": "Tacos", "kind": "expense", "parent_id": sub["id"]},
    )
    assert res.status_code == 422  # third level rejected


async def test_cat07_credit_card_method_requires_card(client):
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/catalogs/payment-methods",
        headers=ctx["headers"],
        json={"name": "Mi tarjeta", "type": "credit_card"},
    )
    assert res.status_code == 422


async def test_glo03_delete_only_without_references(client):
    ctx = await bootstrap_space(client)
    cat = ctx["categories"]["Salud"]
    pm = ctx["methods"]["Efectivo"]

    res = await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-01",
            "amount": "150.00",
            "currency": "MXN",
            "category_id": cat["id"],
            "payment_method_id": pm["id"],
            "description": "Farmacia",
        },
    )
    assert res.status_code == 201

    # With references: physical delete blocked (GLO-03).
    res = await client.delete(f"/api/v1/catalogs/categories/{cat['id']}", headers=ctx["headers"])
    assert res.status_code == 409
    res = await client.delete(
        f"/api/v1/catalogs/payment-methods/{pm['id']}", headers=ctx["headers"]
    )
    assert res.status_code == 409

    # Without references: physical delete allowed.
    free_cat = ctx["categories"]["Ropa"]
    res = await client.delete(
        f"/api/v1/catalogs/categories/{free_cat['id']}", headers=ctx["headers"]
    )
    assert res.status_code == 204


async def test_payment_method_update_name(client):
    """PATCH actualiza el nombre de un método de pago."""
    ctx = await bootstrap_space(client)
    method_id = ctx["methods"]["Efectivo"]["id"]

    res = await client.patch(
        f"/api/v1/catalogs/payment-methods/{method_id}",
        headers=ctx["headers"],
        json={"name": "Efectivo MXN"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Efectivo MXN"


async def test_payment_method_delete_no_refs(client):
    """GLO-03: un método sin transacciones se elimina físicamente."""
    ctx = await bootstrap_space(client)
    res = await client.post(
        "/api/v1/catalogs/payment-methods",
        headers=ctx["headers"],
        json={"name": "Vales de despensa", "type": "prepaid"},
    )
    assert res.status_code == 201
    method_id = res.json()["id"]

    res = await client.delete(
        f"/api/v1/catalogs/payment-methods/{method_id}",
        headers=ctx["headers"],
    )
    assert res.status_code == 204

    # Ya no aparece ni con include_inactive
    methods = (
        await client.get(
            "/api/v1/catalogs/payment-methods?include_inactive=true",
            headers=ctx["headers"],
        )
    ).json()
    assert not any(m["id"] == method_id for m in methods)


async def test_payment_method_delete_with_refs_returns_409(client):
    """GLO-03: DELETE devuelve 409 cuando el método tiene transacciones."""
    ctx = await bootstrap_space(client)
    pm = ctx["methods"]["Débito"]
    cat_id = ctx["categories"]["Comida"]["id"]

    await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-01",
            "amount": "200.00",
            "currency": "MXN",
            "category_id": cat_id,
            "payment_method_id": pm["id"],
        },
    )

    res = await client.delete(
        f"/api/v1/catalogs/payment-methods/{pm['id']}",
        headers=ctx["headers"],
    )
    assert res.status_code == 409


async def test_payment_method_deactivate_after_409(client):
    """Flujo GLO-03: 409 en DELETE → cliente desactiva; el método queda inactivo."""
    ctx = await bootstrap_space(client)
    pm = ctx["methods"]["Transferencia"]
    cat_id = ctx["categories"]["Servicios"]["id"]

    await client.post(
        "/api/v1/transactions",
        headers=ctx["headers"],
        json={
            "type": "expense",
            "date": "2026-06-01",
            "amount": "150.00",
            "currency": "MXN",
            "category_id": cat_id,
            "payment_method_id": pm["id"],
        },
    )

    # DELETE rechazado
    res = await client.delete(
        f"/api/v1/catalogs/payment-methods/{pm['id']}",
        headers=ctx["headers"],
    )
    assert res.status_code == 409

    # El cliente desactiva en lugar de eliminar
    res = await client.patch(
        f"/api/v1/catalogs/payment-methods/{pm['id']}",
        headers=ctx["headers"],
        json={"is_active": False},
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    # Aparece inactivo con include_inactive; no aparece sin él
    with_inactive = (
        await client.get(
            "/api/v1/catalogs/payment-methods?include_inactive=true",
            headers=ctx["headers"],
        )
    ).json()
    assert any(m["id"] == pm["id"] and not m["is_active"] for m in with_inactive)

    without_inactive = (
        await client.get("/api/v1/catalogs/payment-methods", headers=ctx["headers"])
    ).json()
    assert not any(m["id"] == pm["id"] for m in without_inactive)


async def test_esp03_viewer_cannot_mutate_catalogs(client, db_session):
    """ESP-03/caso 8: viewer ve catálogos pero no puede crear/editar/borrar."""
    ctx = await bootstrap_space(client)
    viewer = uuid.uuid4()
    viewer_auth = auth_headers(viewer, "viewer@example.com")
    await client.get("/api/v1/me", headers=viewer_auth)
    db_session.add(
        SpaceMember(space_id=uuid.UUID(ctx["space_id"]), user_id=viewer, role=SpaceRole.viewer)
    )
    await db_session.commit()
    viewer_headers = {**viewer_auth, "X-Space-Id": ctx["space_id"]}

    res = await client.get("/api/v1/catalogs/categories", headers=viewer_headers)
    assert res.status_code == 200

    res = await client.post(
        "/api/v1/catalogs/categories",
        headers=viewer_headers,
        json={"name": "Mascotas", "kind": "expense"},
    )
    assert res.status_code == 403

    cat_id = ctx["categories"]["Comida"]["id"]
    res = await client.patch(
        f"/api/v1/catalogs/categories/{cat_id}",
        headers=viewer_headers,
        json={"name": "Hackeada"},
    )
    assert res.status_code == 403
    res = await client.delete(f"/api/v1/catalogs/categories/{cat_id}", headers=viewer_headers)
    assert res.status_code == 403
