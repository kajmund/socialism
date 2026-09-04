"""Help chat must not leak another tenant's data via customer_id or view params."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona, Population, PopulationMember
from app.schemas.domain import HelpViewContext
from app.services.help_read_context import build_help_context
from app.services.prompt_store import ensure_default_configurations


@pytest.mark.asyncio
async def test_help_context_denies_other_kund_persona() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        await ensure_default_configurations(session)
        session.add(
            Persona(
                id="bolag-secret-persona",
                customer_id=2,
                name="Bolag hemlig",
                age=40,
                occ="VD",
                district="Göteborg",
                quote="SECRET_BOLAG_QUOTE_XYZ",
                origin="manuell",
            )
        )
        await session.commit()

        view = HelpViewContext(
            path="/personas/bolag-secret-persona",
            view_key="personas.detail",
            label="Persona",
            params={"id": "bolag-secret-persona"},
            search={},
        )
        text = await build_help_context(
            session,
            view=view,
            query="visa persona",
            customer_id=1,
        )
        assert "SECRET_BOLAG_QUOTE_XYZ" not in text
        assert "Not available for this tenant" in text

    await engine.dispose()


async def _seed_foreign_population(session: AsyncSession) -> int:
    session.add(
        Persona(
            id="bolag-pop-persona",
            customer_id=2,
            name="Bolag medlem",
            age=40,
            occ="VD",
            district="Göteborg",
            quote="hej",
            origin="manuell",
        )
    )
    pop = Population(
        customer_id=2,
        name="SECRET_BOLAG_POP_NAME",
        size=17,
        versions=3,
        fingerprint=[[100, 0, 0]],
        recipe={},
    )
    session.add(pop)
    await session.flush()
    session.add(
        PopulationMember(
            population_id=pop.id,
            persona_id="bolag-pop-persona",
            name="Bolag medlem",
            initials="BM",
            age=40,
            occ="VD",
            district="Göteborg",
            trait="hej",
        )
    )
    await session.commit()
    return pop.id


@pytest.mark.asyncio
async def test_help_context_denies_other_kund_population() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        await ensure_default_configurations(session)
        pop_id = await _seed_foreign_population(session)

        view = HelpViewContext(
            path=f"/populations/{pop_id}",
            view_key="populations.detail",
            label="Population",
            params={"id": str(pop_id)},
            search={},
        )
        text = await build_help_context(
            session,
            view=view,
            query="visa population",
            customer_id=1,
        )
        assert "SECRET_BOLAG_POP_NAME" not in text
        assert "size: 17" not in text
        assert "versions: 3" not in text
        assert "Not available for this tenant" in text
        assert "- Populations: 0" in text

    await engine.dispose()


@pytest.mark.asyncio
async def test_help_context_includes_own_kund_population() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        await ensure_default_configurations(session)
        session.add(
            Persona(
                id="own-pop-persona",
                customer_id=1,
                name="Egen medlem",
                age=32,
                occ="Lärare",
                district="Centrum",
                quote="hej",
                origin="manuell",
            )
        )
        pop = Population(
            customer_id=1,
            name="Egen synlig pop",
            size=4,
            versions=1,
            fingerprint=[[100, 0, 0]],
            recipe={},
        )
        session.add(pop)
        await session.flush()
        session.add(
            PopulationMember(
                population_id=pop.id,
                persona_id="own-pop-persona",
                name="Egen medlem",
                initials="EM",
                age=32,
                occ="Lärare",
                district="Centrum",
                trait="hej",
            )
        )
        await session.commit()

        view = HelpViewContext(
            path=f"/populations/{pop.id}",
            view_key="populations.detail",
            label="Population",
            params={"id": str(pop.id)},
            search={},
        )
        text = await build_help_context(
            session,
            view=view,
            query="visa population",
            customer_id=1,
        )
        assert "Egen synlig pop" in text
        assert "size: 4" in text
        assert "- Populations: 1" in text
        assert "Not available for this tenant" not in text

    await engine.dispose()
