"""Auth dependency acceptance: 401 without token, 403 when not provisioned."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.config import settings
from app.database.base import Base
from app.database.models import UserAccount
from app.database.session import get_session

TEST_JWT_SECRET = "test-supabase-jwt-secret-not-real"


def _mint_token(*, sub: str, email: str = "probe@example.com") -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
async def auth_probe_client():
    """Minimal app with one protected route — production routers stay open in Fas A."""
    settings.supabase_jwt_secret = TEST_JWT_SECRET

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    @app.get("/_auth_probe")
    async def auth_probe(user: UserAccount = Depends(get_current_user)) -> dict:
        return {"id": user.id, "email": user.email, "role": user.role}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_auth_probe_without_authorization_returns_401(auth_probe_client) -> None:
    client, _ = auth_probe_client
    response = await client.get("/_auth_probe")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_probe_valid_token_without_user_account_returns_403(
    auth_probe_client,
) -> None:
    client, _ = auth_probe_client
    token = _mint_token(sub="00000000-0000-4000-8000-000000000001")
    response = await client.get(
        "/_auth_probe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "not_provisioned"


@pytest.mark.asyncio
async def test_auth_probe_provisioned_user_returns_200(auth_probe_client) -> None:
    client, session_factory = auth_probe_client
    user_id = "00000000-0000-4000-8000-000000000002"
    async with session_factory() as session:
        session.add(
            UserAccount(
                id=user_id,
                email="admin@example.com",
                role="admin",
                kund_id=None,
            )
        )
        await session.commit()

    token = _mint_token(sub=user_id, email="admin@example.com")
    response = await client.get(
        "/_auth_probe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == user_id
    assert body["role"] == "admin"
