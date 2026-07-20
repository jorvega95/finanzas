"""Test fixtures: in-memory SQLite DB, app client and JWT helpers.

Production runs on Postgres (Supabase); tests use SQLite + aiosqlite with the
same SQLAlchemy models (portable types only — enforced by convention).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.deps import get_db
from app.main import app
from app.models import Base

JWT_SECRET = "test-secret-0123456789abcdef0123456789abcdef"


@pytest.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def make_token(user_id: uuid.UUID | None = None, email: str = "user@example.com") -> str:
    # exp/iat son obligatorios en la verificación (app.core.security.REQUIRED_CLAIMS),
    # igual que en los tokens que emite Supabase. El exp es deliberadamente
    # amplio: varios tests avanzan el reloj con freeze_time y la expiración del
    # token no es lo que están probando.
    now = datetime.now(UTC)
    return pyjwt.encode(
        {
            "sub": str(user_id or uuid.uuid4()),
            "aud": "authenticated",
            "email": email,
            "user_metadata": {},
            "iat": now,
            "exp": now + timedelta(days=3650),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def auth_headers(user_id: uuid.UUID | None = None, email: str = "user@example.com") -> dict:
    return {"Authorization": f"Bearer {make_token(user_id, email)}"}


async def bootstrap_space(client, user_id: uuid.UUID | None = None) -> dict:
    """Provision a user (ESP-01) and return ready-to-use request context:
    headers (auth + X-Space-Id), space_id, and seeded catalogs by name."""
    user_id = user_id or uuid.uuid4()
    base_headers = auth_headers(user_id)
    me = (await client.get("/api/v1/me", headers=base_headers)).json()
    space_id = me["spaces"][0]["id"]
    headers = {**base_headers, "X-Space-Id": space_id}

    categories = (await client.get("/api/v1/catalogs/categories", headers=headers)).json()
    methods = (await client.get("/api/v1/catalogs/payment-methods", headers=headers)).json()
    card_types = (await client.get("/api/v1/catalogs/card-types", headers=headers)).json()
    return {
        "user_id": user_id,
        "space_id": space_id,
        "headers": headers,
        # CAT-02 siembra "Otros" en gasto y en ingreso: indexar solo por nombre
        # colapsaba ambas y la ganadora dependía del orden de la query. Las de
        # gasto tienen prioridad (uso predominante); las de ingreso van aparte.
        "categories": {
            c["name"]: c for c in sorted(categories, key=lambda c: c["kind"] == "expense")
        },
        "income_categories": {c["name"]: c for c in categories if c["kind"] == "income"},
        "expense_categories": {c["name"]: c for c in categories if c["kind"] == "expense"},
        "methods": {m["name"]: m for m in methods},
        # CAT-08: seeded card types keyed by behavior for convenience.
        "card_types": {ct["name"]: ct for ct in card_types},
        "card_type_by_behavior": {ct["behavior"]: ct for ct in card_types},
    }
