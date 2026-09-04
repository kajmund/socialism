"""PanelExpertProfile and Population are scoped per kund."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import PanelExpertProfile, Persona, Population
from app.services.dd.default_experts import DEFAULT_EXPERT_SPECS, ensure_default_expert_personas
from app.services.dd.expert_keys import expert_persona_id, expert_role_key
from app.services.kund_store import (
    bolag_demo_customer_id,
    default_os_customer_id,
    ensure_default_kunder,
)
from app.services.panel.expert_profiles_store import (
    ensure_expert_profile_defaults,
    get_expert_profiles,
)
from app.services.panel.module_defaults import ensure_module_panel_defaults
from app.services.panel.spinndoctor_profile import SPINNDOCTOR_KEY, require_spinndoctor_profile
from app.services.population_persist import allocate_unique_population_name
from app.serializers import utcnow


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
    async with factory() as db:
        await ensure_default_kunder(db)
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_module_panel_defaults_persist_after_session_close():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as seed:
        await ensure_module_panel_defaults(seed)
        os_id = await default_os_customer_id(seed)
        bolag_id = await bolag_demo_customer_id(seed)
    async with factory() as later:
        os_spin = await require_spinndoctor_profile(later, customer_id=os_id)
        bolag_spin = await require_spinndoctor_profile(later, customer_id=bolag_id)
        assert os_spin.id != bolag_spin.id
        os_rows = await get_expert_profiles(later, "dd", customer_id=os_id)
        bolag_rows = await get_expert_profiles(later, "dd", customer_id=bolag_id)
        assert os_rows
        assert bolag_rows
    await engine.dispose()


@pytest.mark.asyncio
async def test_startup_seeds_catalog_per_customer(session: AsyncSession):
    await ensure_module_panel_defaults(session)
    os_id = await default_os_customer_id(session)
    bolag_id = await bolag_demo_customer_id(session)

    os_rows = await get_expert_profiles(session, "dd", customer_id=os_id)
    bolag_rows = await get_expert_profiles(session, "dd", customer_id=bolag_id)
    assert {row.key for row in os_rows} == {row.key for row in bolag_rows}
    assert {row.id for row in os_rows}.isdisjoint({row.id for row in bolag_rows})

    os_spin = await require_spinndoctor_profile(session, customer_id=os_id)
    bolag_spin = await require_spinndoctor_profile(session, customer_id=bolag_id)
    assert os_spin.id != bolag_spin.id
    assert os_spin.key == bolag_spin.key == SPINNDOCTOR_KEY


@pytest.mark.asyncio
async def test_same_expert_key_is_allowed_for_two_customers(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    bolag_id = await bolag_demo_customer_id(session)
    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=os_id
    )
    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=bolag_id
    )
    key = expert_role_key(DEFAULT_EXPERT_SPECS[0]["name"])
    rows = list(
        (
            await session.execute(
                select(PanelExpertProfile).where(PanelExpertProfile.key == key)
            )
        ).scalars().all()
    )
    assert {row.customer_id for row in rows} == {os_id, bolag_id}


@pytest.mark.asyncio
async def test_expert_persona_ids_include_customer(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    bolag_id = await bolag_demo_customer_id(session)
    await ensure_default_expert_personas(session, customer_id=os_id)
    await ensure_default_expert_personas(session, customer_id=bolag_id)
    name = DEFAULT_EXPERT_SPECS[0]["name"]
    os_persona = await session.get(Persona, expert_persona_id(os_id, name))
    bolag_persona = await session.get(Persona, expert_persona_id(bolag_id, name))
    assert os_persona is not None
    assert bolag_persona is not None
    assert os_persona.id != bolag_persona.id
    assert os_persona.customer_id == os_id
    assert bolag_persona.customer_id == bolag_id


@pytest.mark.asyncio
async def test_population_name_unique_per_customer(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    bolag_id = await bolag_demo_customer_id(session)
    session.add(
        Population(
            customer_id=os_id,
            name="Samma namn",
            size=0,
            versions=1,
            fingerprint=[],
            recipe={},
            updated_at=utcnow(),
        )
    )
    session.add(
        Population(
            customer_id=bolag_id,
            name="Samma namn",
            size=0,
            versions=1,
            fingerprint=[],
            recipe={},
            updated_at=utcnow(),
        )
    )
    await session.commit()
    assert (
        await allocate_unique_population_name(session, "Samma namn", customer_id=os_id)
        == "Samma namn (2)"
    )
    assert (
        await allocate_unique_population_name(
            session, "Samma namn", customer_id=bolag_id
        )
        == "Samma namn (2)"
    )
