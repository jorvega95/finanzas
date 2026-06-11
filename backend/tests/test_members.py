"""Fase 5 tests: ESP-04..ESP-07 (invitaciones, roles, salida, borrado)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.spaces import SpaceInvite
from app.models.transactions import Transaction
from tests.conftest import auth_headers, bootstrap_space


async def create_shared(client, headers, name="Familia"):
    res = await client.post("/api/v1/spaces", headers=headers, json={"name": name})
    assert res.status_code == 201
    return res.json()


async def invite(client, headers, space_id, email, role="editor", expected=201):
    res = await client.post(
        f"/api/v1/spaces/{space_id}/invites",
        headers=headers,
        json={"email": email, "role": role},
    )
    assert res.status_code == expected, res.text
    return res.json() if expected == 201 else None


async def test_esp04_invite_claim_flow(client):
    """ESP-04: token de un solo uso; el email debe coincidir; re-invitar
    reemplaza la pendiente."""
    owner = await bootstrap_space(client)
    shared = await create_shared(client, owner["headers"])
    # La amiga ya tiene cuenta ANTES de la invitación (sin auto-claim).
    friend_auth = auth_headers(uuid.uuid4(), "amiga@example.com")
    await client.get("/api/v1/me", headers=friend_auth)

    first = await invite(client, owner["headers"], shared["id"], "amiga@example.com")
    # Re-invitar al mismo email reemplaza la anterior (ESP-04).
    second = await invite(
        client, owner["headers"], shared["id"], "amiga@example.com", role="viewer"
    )
    pending = (
        await client.get(f"/api/v1/spaces/{shared['id']}/invites", headers=owner["headers"])
    ).json()
    assert len(pending) == 1
    assert pending[0]["role"] == "viewer"

    # El token viejo ya no existe.
    res = await client.post(
        "/api/v1/invites/claim", headers=friend_auth, json={"token": first["token"]}
    )
    assert res.status_code == 404

    # Un usuario con OTRO email no puede reclamar (404, sin filtrar).
    stranger_auth = auth_headers(uuid.uuid4(), "otra@example.com")
    await client.get("/api/v1/me", headers=stranger_auth)
    res = await client.post(
        "/api/v1/invites/claim", headers=stranger_auth, json={"token": second["token"]}
    )
    assert res.status_code == 404

    # El invitado correcto reclama y queda con el rol invitado.
    res = await client.post(
        "/api/v1/invites/claim", headers=friend_auth, json={"token": second["token"]}
    )
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"

    # Un solo uso: segundo claim falla.
    res = await client.post(
        "/api/v1/invites/claim", headers=friend_auth, json={"token": second["token"]}
    )
    assert res.status_code == 404


async def test_esp04_expired_invite_and_claim_at_registration(client, db_session):
    owner = await bootstrap_space(client)
    shared = await create_shared(client, owner["headers"])
    body = await invite(client, owner["headers"], shared["id"], "nueva@example.com")

    # Expirada ⇒ no reclamable.
    row = await db_session.get(SpaceInvite, uuid.UUID(body["id"]))
    row.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()
    user_auth = auth_headers(uuid.uuid4(), "nueva@example.com")
    await client.get("/api/v1/me", headers=user_auth)
    res = await client.post(
        "/api/v1/invites/claim", headers=user_auth, json={"token": body["token"]}
    )
    assert res.status_code == 404

    # Vigente ⇒ se reclama sola al registrarse (ESP-04).
    await invite(client, owner["headers"], shared["id"], "auto@example.com")
    auto_auth = auth_headers(uuid.uuid4(), "auto@example.com")
    me = (await client.get("/api/v1/me", headers=auto_auth)).json()
    names = {s["name"] for s in me["spaces"]}
    assert "Familia" in names


async def test_esp03_only_owner_invites(client):
    owner = await bootstrap_space(client)
    shared = await create_shared(client, owner["headers"])
    await invite(client, owner["headers"], shared["id"], "editor@example.com")

    editor_auth = auth_headers(uuid.uuid4(), "editor@example.com")
    await client.get("/api/v1/me", headers=editor_auth)  # auto-claim editor

    # Editor no puede invitar ni listar invitaciones ni cambiar roles (403).
    res = await client.post(
        f"/api/v1/spaces/{shared['id']}/invites",
        headers=editor_auth,
        json={"email": "x@example.com", "role": "editor"},
    )
    assert res.status_code == 403
    res = await client.get(f"/api/v1/spaces/{shared['id']}/invites", headers=editor_auth)
    assert res.status_code == 403

    # No-miembro: 404 (GLO-05).
    outsider_auth = auth_headers(uuid.uuid4(), "out@example.com")
    await client.get("/api/v1/me", headers=outsider_auth)
    res = await client.get(f"/api/v1/spaces/{shared['id']}/invites", headers=outsider_auth)
    assert res.status_code == 404


async def test_esp05_last_owner_protected_and_transfer(client):
    owner = await bootstrap_space(client)
    shared = await create_shared(client, owner["headers"])
    await invite(client, owner["headers"], shared["id"], "co@example.com")
    co_id = uuid.uuid4()
    co_auth = auth_headers(co_id, "co@example.com")
    await client.get("/api/v1/me", headers=co_auth)

    # El único owner no puede degradarse ni salir (ESP-05).
    res = await client.patch(
        f"/api/v1/spaces/{shared['id']}/members/{owner['user_id']}",
        headers=owner["headers"],
        json={"role": "editor"},
    )
    assert res.status_code == 422
    res = await client.delete(
        f"/api/v1/spaces/{shared['id']}/members/{owner['user_id']}",
        headers=owner["headers"],
    )
    assert res.status_code == 422

    # Transferencia: promover al otro a owner, luego sí puede degradarse.
    res = await client.patch(
        f"/api/v1/spaces/{shared['id']}/members/{co_id}",
        headers=owner["headers"],
        json={"role": "owner"},
    )
    assert res.status_code == 200
    res = await client.patch(
        f"/api/v1/spaces/{shared['id']}/members/{owner['user_id']}",
        headers=owner["headers"],
        json={"role": "editor"},
    )
    assert res.status_code == 200

    members = (
        await client.get(f"/api/v1/spaces/{shared['id']}/members", headers=owner["headers"])
    ).json()
    roles = {m["email"]: m["role"] for m in members}
    assert roles["co@example.com"] == "owner"


async def test_esp07_removed_member_transactions_persist(client, db_session):
    owner = await bootstrap_space(client)
    shared = await create_shared(client, owner["headers"])
    await invite(client, owner["headers"], shared["id"], "temp@example.com")
    temp_id = uuid.uuid4()
    temp_auth = auth_headers(temp_id, "temp@example.com")
    await client.get("/api/v1/me", headers=temp_auth)

    # El editor temporal registra un gasto en el espacio compartido.
    temp_headers = {**temp_auth, "X-Space-Id": shared["id"]}
    cats = (await client.get("/api/v1/catalogs/categories", headers=temp_headers)).json()
    pms = (await client.get("/api/v1/catalogs/payment-methods", headers=temp_headers)).json()
    res = await client.post(
        "/api/v1/transactions",
        headers=temp_headers,
        json={
            "type": "expense",
            "date": "2026-06-01",
            "amount": "100.00",
            "currency": "MXN",
            "category_id": cats[0]["id"],
            "payment_method_id": pms[0]["id"],
        },
    )
    assert res.status_code == 201
    txn_id = res.json()["id"]

    # El owner lo remueve; la transacción queda con su created_by (ESP-07).
    res = await client.delete(
        f"/api/v1/spaces/{shared['id']}/members/{temp_id}", headers=owner["headers"]
    )
    assert res.status_code == 204
    txn = await db_session.get(Transaction, uuid.UUID(txn_id))
    assert txn is not None
    assert txn.created_by == temp_id

    # El removido ya no ve el espacio (404, GLO-05).
    res = await client.get(f"/api/v1/spaces/{shared['id']}", headers=temp_auth)
    assert res.status_code == 404

    # Un miembro puede salirse a sí mismo (no siendo último owner).
    await invite(client, owner["headers"], shared["id"], "leave@example.com")
    leaver_id = uuid.uuid4()
    leaver_auth = auth_headers(leaver_id, "leave@example.com")
    await client.get("/api/v1/me", headers=leaver_auth)
    res = await client.delete(
        f"/api/v1/spaces/{shared['id']}/members/{leaver_id}", headers=leaver_auth
    )
    assert res.status_code == 204


async def test_esp06_delete_space_with_confirmation(client, db_session):
    """ESP-06: confirmación con nombre exacto, cascada y notificación.
    ESP-01: el personal jamás se borra."""
    from app.models.reminders import Reminder, ReminderKind

    owner = await bootstrap_space(client)
    personal_id = owner["space_id"]
    shared = await create_shared(client, owner["headers"])
    await invite(client, owner["headers"], shared["id"], "miembro@example.com")
    member_auth = auth_headers(uuid.uuid4(), "miembro@example.com")
    await client.get("/api/v1/me", headers=member_auth)

    # Personal: nunca (ESP-01).
    res = await client.request(
        "DELETE",
        f"/api/v1/spaces/{personal_id}",
        headers=owner["headers"],
        json={"confirm_name": "Personal"},
    )
    assert res.status_code == 422

    # Nombre incorrecto: 422 (ESP-06).
    res = await client.request(
        "DELETE",
        f"/api/v1/spaces/{shared['id']}",
        headers=owner["headers"],
        json={"confirm_name": "Otra cosa"},
    )
    assert res.status_code == 422

    # Confirmado: borra en cascada y notifica.
    res = await client.request(
        "DELETE",
        f"/api/v1/spaces/{shared['id']}",
        headers=owner["headers"],
        json={"confirm_name": "Familia"},
    )
    assert res.status_code == 204
    res = await client.get(f"/api/v1/spaces/{shared['id']}", headers=owner["headers"])
    assert res.status_code == 404

    notifications = (
        (await db_session.execute(select(Reminder).where(Reminder.kind == ReminderKind.custom)))
        .scalars()
        .all()
    )
    assert len(notifications) == 2  # owner + miembro (ESP-06)
    assert all("Familia" in n.message for n in notifications)
