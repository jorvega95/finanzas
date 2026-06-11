"""Fase 0 tests: ESP-01, ESP-02, ESP-03 (rename), GLO-05 (404 for non-members)."""

import uuid

from sqlalchemy import select

from app.models.spaces import Profile, SpaceMember, SpaceRole
from tests.conftest import auth_headers


async def test_esp01_first_request_provisions_profile_and_personal_space(client):
    """ESP-01: first authenticated request creates profile + personal space
    'Personal' + owner membership, and sets default_space_id."""
    user_id = uuid.uuid4()
    res = await client.get("/api/v1/me", headers=auth_headers(user_id, "ana@example.com"))
    assert res.status_code == 200
    body = res.json()
    assert body["profile"]["id"] == str(user_id)
    assert body["profile"]["email"] == "ana@example.com"
    assert body["profile"]["display_name"] == "ana"
    assert len(body["spaces"]) == 1
    space = body["spaces"][0]
    assert space["name"] == "Personal"
    assert space["type"] == "personal"
    assert space["role"] == "owner"
    assert space["base_currency"] == "MXN"  # FX-01 default
    assert space["timezone"] == "America/Mexico_City"  # GLO-02
    assert body["profile"]["default_space_id"] == space["id"]


async def test_esp01_provisioning_is_idempotent(client, db_session):
    """ESP-01/ESP-02: repeated requests never create a second personal space."""
    user_id = uuid.uuid4()
    headers = auth_headers(user_id)
    for _ in range(3):
        res = await client.get("/api/v1/me", headers=headers)
        assert res.status_code == 200
    assert len(res.json()["spaces"]) == 1
    profiles = (await db_session.execute(select(Profile))).scalars().all()
    assert len(profiles) == 1


async def test_cat02_seed_catalogs_on_personal_space(client, db_session):
    """CAT-02: every new space gets the seed categories and payment methods."""
    from app.models.catalogs import Category, CategoryKind, PaymentMethod

    user_id = uuid.uuid4()
    res = await client.get("/api/v1/me", headers=auth_headers(user_id))
    space_id = uuid.UUID(res.json()["spaces"][0]["id"])

    cats = (
        (await db_session.execute(select(Category).where(Category.space_id == space_id)))
        .scalars()
        .all()
    )
    expense = {c.name for c in cats if c.kind == CategoryKind.expense}
    income = {c.name for c in cats if c.kind == CategoryKind.income}
    assert expense == {
        "Comida",
        "Súper",
        "Transporte",
        "Vivienda",
        "Servicios",
        "Salud",
        "Entretenimiento",
        "Ropa",
        "Educación",
        "Regalos",
        "Otros",
    }
    assert income == {"Nómina", "Freelance", "Intereses", "Otros"}
    # CAT-03: every expense category carries a nature; income ones do not.
    assert all(c.expense_nature is not None for c in cats if c.kind == CategoryKind.expense)
    assert all(c.expense_nature is None for c in cats if c.kind == CategoryKind.income)

    methods = (
        (await db_session.execute(select(PaymentMethod).where(PaymentMethod.space_id == space_id)))
        .scalars()
        .all()
    )
    assert {m.name for m in methods} == {"Efectivo", "Débito", "Transferencia"}


async def test_esp02_create_shared_space(client):
    """ESP-02: a user can create N shared spaces; they are seeded too (CAT-02)."""
    user_id = uuid.uuid4()
    headers = auth_headers(user_id)
    await client.get("/api/v1/me", headers=headers)

    res = await client.post("/api/v1/spaces", headers=headers, json={"name": "Familia"})
    assert res.status_code == 201
    body = res.json()
    assert body["type"] == "shared"
    assert body["role"] == "owner"

    res = await client.get("/api/v1/spaces", headers=headers)
    assert len(res.json()) == 2


async def test_glo05_non_member_gets_404_not_403(client):
    """GLO-05 / mandatory case 8: a user without membership receives 404."""
    owner = uuid.uuid4()
    res = await client.get("/api/v1/me", headers=auth_headers(owner))
    space_id = res.json()["spaces"][0]["id"]

    intruder = uuid.uuid4()
    headers = auth_headers(intruder, "intruder@example.com")
    await client.get("/api/v1/me", headers=headers)

    res = await client.get(f"/api/v1/spaces/{space_id}", headers=headers)
    assert res.status_code == 404
    res = await client.patch(f"/api/v1/spaces/{space_id}", headers=headers, json={"name": "hacked"})
    assert res.status_code == 404


async def test_esp03_rename_is_owner_only(client, db_session):
    """ESP-03: editor can see the space but cannot rename it (403)."""
    owner = uuid.uuid4()
    res = await client.get("/api/v1/me", headers=auth_headers(owner))
    space_id = res.json()["spaces"][0]["id"]

    editor = uuid.uuid4()
    editor_headers = auth_headers(editor, "editor@example.com")
    await client.get("/api/v1/me", headers=editor_headers)
    db_session.add(SpaceMember(space_id=uuid.UUID(space_id), user_id=editor, role=SpaceRole.editor))
    await db_session.commit()

    res = await client.get(f"/api/v1/spaces/{space_id}", headers=editor_headers)
    assert res.status_code == 200

    res = await client.patch(
        f"/api/v1/spaces/{space_id}", headers=editor_headers, json={"name": "Nuevo"}
    )
    assert res.status_code == 403

    res = await client.patch(
        f"/api/v1/spaces/{space_id}", headers=auth_headers(owner), json={"name": "Mío"}
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Mío"


async def test_auth_required(client):
    res = await client.get("/api/v1/me")
    assert res.status_code == 401
    res = await client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
