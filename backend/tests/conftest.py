"""Test fixtures: in-memory SQLite DB, app client and JWT helpers.

Production runs on Postgres (Supabase); tests use SQLite + aiosqlite with the
same SQLAlchemy models (portable types only — enforced by convention).
"""

import os
import uuid

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
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
    return pyjwt.encode(
        {
            "sub": str(user_id or uuid.uuid4()),
            "aud": "authenticated",
            "email": email,
            "user_metadata": {},
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def auth_headers(user_id: uuid.UUID | None = None, email: str = "user@example.com") -> dict:
    return {"Authorization": f"Bearer {make_token(user_id, email)}"}
