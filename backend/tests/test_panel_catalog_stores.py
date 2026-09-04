"""Panel sub-question and expert-profile stores (Fas 2a — additive)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import PanelExpertProfile, PanelSubQuestion
from app.services.dd.default_experts import DEFAULT_EXPERT_SPECS
from app.services.dd.expert_keys import expert_role_key
from app.services.dd.sub_questions import DD_SUB_QUESTION_DEFAULTS
from app.services.kund_store import default_os_customer_id, ensure_default_kunder
from app.services.panel.expert_profiles_store import (
    create_expert_profile,
    ensure_expert_profile_defaults,
    get_expert_profiles,
    update_expert_profile,
)
from app.services.panel.sub_questions_store import (
    create_sub_question,
    ensure_sub_question_defaults,
    get_sub_questions,
    update_sub_question,
)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        await ensure_default_kunder(db)
        yield db
    await engine.dispose()


async def _customer_id(session: AsyncSession) -> int:
    return await default_os_customer_id(session)


@pytest.mark.asyncio
async def test_ensure_sub_question_defaults_inserts_once(session: AsyncSession):
    added = await ensure_sub_question_defaults(session, "dd", DD_SUB_QUESTION_DEFAULTS)
    assert added == len(DD_SUB_QUESTION_DEFAULTS)

    again = await ensure_sub_question_defaults(session, "dd", DD_SUB_QUESTION_DEFAULTS)
    assert again == 0

    rows = await get_sub_questions(session, "dd")
    assert [r.key for r in rows] == [d.key for d in DD_SUB_QUESTION_DEFAULTS]
    assert [r.label for r in rows] == [d.label for d in DD_SUB_QUESTION_DEFAULTS]


@pytest.mark.asyncio
async def test_ensure_sub_question_defaults_does_not_overwrite(session: AsyncSession):
    await ensure_sub_question_defaults(session, "dd", DD_SUB_QUESTION_DEFAULTS)
    result = await session.execute(
        select(PanelSubQuestion).where(
            PanelSubQuestion.module == "dd",
            PanelSubQuestion.key == "legal_risk",
        )
    )
    row = result.scalar_one()
    row.label = "Edited legal risk"
    await session.commit()

    await ensure_sub_question_defaults(session, "dd", DD_SUB_QUESTION_DEFAULTS)
    await session.refresh(row)
    assert row.label == "Edited legal risk"


@pytest.mark.asyncio
async def test_ensure_expert_profile_defaults_inserts_once(session: AsyncSession):
    cid = await _customer_id(session)
    added = await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    assert added == len(DEFAULT_EXPERT_SPECS)

    again = await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    assert again == 0

    rows = await get_expert_profiles(session, "dd", customer_id=cid)
    assert len(rows) == 4
    assert rows[0].key == expert_role_key(DEFAULT_EXPERT_SPECS[0]["name"])
    assert rows[0].name == DEFAULT_EXPERT_SPECS[0]["name"]
    assert rows[0].kompetensomrade == DEFAULT_EXPERT_SPECS[0]["kompetensomrade"]
    assert rows[0].modules == ["dd"]
    assert await get_expert_profiles(session, "politik", customer_id=cid) == []


@pytest.mark.asyncio
async def test_ensure_expert_profile_defaults_does_not_overwrite(session: AsyncSession):
    cid = await _customer_id(session)
    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    key = expert_role_key(DEFAULT_EXPERT_SPECS[0]["name"])
    result = await session.execute(
        select(PanelExpertProfile).where(
            PanelExpertProfile.customer_id == cid,
            PanelExpertProfile.key == key,
        )
    )
    row = result.scalar_one()
    row.description = "Edited description"
    await session.commit()

    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    await session.refresh(row)
    assert row.description == "Edited description"


@pytest.mark.asyncio
async def test_ensure_expert_profile_defaults_attaches_module_without_duplicate(
    session: AsyncSession,
):
    cid = await _customer_id(session)
    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    key = expert_role_key(DEFAULT_EXPERT_SPECS[0]["name"])
    result = await session.execute(
        select(PanelExpertProfile).where(
            PanelExpertProfile.customer_id == cid,
            PanelExpertProfile.key == key,
        )
    )
    row = result.scalar_one()
    row.description = "Edited description"
    await session.commit()

    attached = await ensure_expert_profile_defaults(
        session, "politik", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    assert attached == len(DEFAULT_EXPERT_SPECS)
    again = await ensure_expert_profile_defaults(
        session, "politik", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    assert again == 0

    await session.refresh(row)
    assert row.description == "Edited description"
    assert row.modules == ["dd", "politik"]

    dd_rows = await get_expert_profiles(session, "dd", customer_id=cid)
    politik_rows = await get_expert_profiles(session, "politik", customer_id=cid)
    assert [r.key for r in dd_rows] == [r.key for r in politik_rows]
    assert len({r.id for r in dd_rows} | {r.id for r in politik_rows}) == 4

    all_rows = (await session.execute(select(PanelExpertProfile))).scalars().all()
    assert len(all_rows) == 4


@pytest.mark.asyncio
async def test_create_and_update_sub_question(session: AsyncSession):
    await ensure_sub_question_defaults(session, "dd", DD_SUB_QUESTION_DEFAULTS)
    row = await create_sub_question(
        session,
        module="dd",
        key="esg",
        label="ESG",
        sort_order=10,
    )
    await session.commit()
    row = await update_sub_question(session, row, label="ESG-risk", active=False)
    await session.commit()
    listed = await get_sub_questions(session, "dd", active_only=False)
    found = next(item for item in listed if item.key == "esg")
    assert found.label == "ESG-risk"
    assert found.active is False
    assert "esg" not in {item.key for item in await get_sub_questions(session, "dd")}


@pytest.mark.asyncio
async def test_create_and_update_expert_profile(session: AsyncSession):
    cid = await _customer_id(session)
    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    row = await create_expert_profile(
        session,
        customer_id=cid,
        module="dd",
        key="esg_expert",
        name="ESG-expert",
        description="Hållbarhet",
        sort_order=10,
    )
    await session.commit()
    row = await update_expert_profile(session, row, description="Klimat")
    await session.commit()
    listed = await get_expert_profiles(session, "dd", customer_id=cid)
    found = next(item for item in listed if item.key == "esg_expert")
    assert found.description == "Klimat"


@pytest.mark.asyncio
async def test_duplicate_sort_order_is_rejected(session: AsyncSession):
    await ensure_sub_question_defaults(session, "dd", DD_SUB_QUESTION_DEFAULTS)
    with pytest.raises(IntegrityError):
        await create_sub_question(
            session,
            module="dd",
            key="esg",
            label="ESG",
            sort_order=0,
        )
    await session.rollback()

    cid = await _customer_id(session)
    await ensure_expert_profile_defaults(
        session, "dd", DEFAULT_EXPERT_SPECS, customer_id=cid
    )
    first = (await get_expert_profiles(session, "dd", customer_id=cid))[0]
    with pytest.raises(IntegrityError):
        await create_expert_profile(
            session,
            customer_id=cid,
            module="politik",
            key=first.key,
            name="Duplicate key",
            sort_order=99,
        )


@pytest.mark.asyncio
async def test_ensure_defaults_skips_taken_sort_order(session: AsyncSession):
    await create_sub_question(
        session, module="dd", key="custom", label="Custom", sort_order=0
    )
    await session.commit()
    added = await ensure_sub_question_defaults(session, "dd", DD_SUB_QUESTION_DEFAULTS)
    assert added == len(DD_SUB_QUESTION_DEFAULTS)
    rows = await get_sub_questions(session, "dd", active_only=False)
    orders = [row.sort_order for row in rows]
    assert len(orders) == len(set(orders))
