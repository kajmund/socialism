"""Kund / Projekt scoping foundation (steps 1–2)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Configuration, Kund, Persona, Projekt
from app.database.session import get_session
from app.main import create_app
from app.services.kund_store import (
    BOLAG_DEMO_KUND_SLUG,
    DEFAULT_PROJEKT_SLUG,
    OS_DEFAULT_KUND_SLUG,
    bolag_demo_customer_id,
    default_os_customer_id,
    ensure_default_kunder,
)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_ensure_default_kunder_seeds_os_and_bolag(session: AsyncSession):
    await ensure_default_kunder(session)

    kunder = list((await session.execute(select(Kund).order_by(Kund.id))).scalars().all())
    assert len(kunder) == 2
    assert kunder[0].slug == OS_DEFAULT_KUND_SLUG
    assert kunder[1].slug == BOLAG_DEMO_KUND_SLUG

    projekt = list(
        (await session.execute(select(Projekt).where(Projekt.customer_id == kunder[0].id)))
        .scalars()
        .all()
    )
    assert len(projekt) == 1
    assert projekt[0].slug == DEFAULT_PROJEKT_SLUG


async def test_default_os_customer_id_is_idempotent(session: AsyncSession):
    first = await default_os_customer_id(session)
    second = await default_os_customer_id(session)
    assert first == second
    assert first >= 1


async def test_bolag_demo_customer_id_distinct_from_os(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    bolag_id = await bolag_demo_customer_id(session)
    assert os_id != bolag_id


async def test_configurations_seeded_with_customer_id(session: AsyncSession):
    from app.services.prompt_store import ensure_default_configurations

    await ensure_default_configurations(session)
    rows = list((await session.execute(select(Configuration))).scalars().all())
    assert rows
    os_id = await default_os_customer_id(session)
    assert all(row.customer_id == os_id for row in rows)


async def test_kunder_api_lists_seeded_tenants():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()

    async def override_get_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/kunder")
        assert listed.status_code == 200
        body = listed.json()
        assert len(body) >= 2
        slugs = {row["slug"] for row in body}
        assert OS_DEFAULT_KUND_SLUG in slugs
        assert BOLAG_DEMO_KUND_SLUG in slugs
        devbrains = next(row for row in body if row["slug"] == OS_DEFAULT_KUND_SLUG)
        assert devbrains["projekt"]
        assert devbrains["projekt"][0]["slug"] == DEFAULT_PROJEKT_SLUG

    await engine.dispose()


async def test_persona_row_requires_customer_id(session: AsyncSession):
    customer_id = await default_os_customer_id(session)
    session.add(
        Persona(
            id="p-scope",
            customer_id=customer_id,
            name="Scope Test",
            age=35,
            occ="Testare",
            district="Centrum",
            quote="",
            origin="manuell",
            profile={"name": "Scope Test"},
        )
    )
    await session.commit()
    row = await session.get(Persona, "p-scope")
    assert row is not None
    assert row.customer_id == customer_id
