"""customer_id resolution for jobs/reports (project before DD campaign)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import DdCampaign, PanelSession, Projekt
from app.schemas.domain import JobCreate
from app.serializers import utcnow
from app.services.customer_scope import (
    customer_id_for_new_job,
    customer_id_for_panel_session,
)
from app.services.kund_store import (
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
        await ensure_default_kunder(s)
        yield s
    await engine.dispose()


async def _add_project(session: AsyncSession, customer_id: int, slug: str) -> Projekt:
    now = utcnow()
    row = Projekt(
        customer_id=customer_id,
        name=slug,
        slug=slug,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _add_campaign(session: AsyncSession, customer_id: int, title: str) -> DdCampaign:
    now = utcnow()
    row = DdCampaign(
        customer_id=customer_id,
        title=title,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _add_panel(
    session: AsyncSession,
    session_id: str,
    *,
    project_id: int | None = None,
    campaign_id: int | None = None,
) -> PanelSession:
    row = PanelSession(
        id=session_id,
        protocol="generic_panel",
        status="draft",
        config={"protocol": "generic_panel", "topic": "t", "expert_slots": []},
        transcript=[],
        scratchpads={},
        project_id=project_id,
        campaign_id=campaign_id,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_panel_session_uses_project_customer_before_default(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    bolag_id = await bolag_demo_customer_id(session)
    projekt = await _add_project(session, bolag_id, "other-customer-proj")
    await _add_panel(session, "ps_project_only", project_id=projekt.id)

    resolved = await customer_id_for_panel_session(session, "ps_project_only")
    assert resolved == bolag_id
    assert resolved != os_id


@pytest.mark.asyncio
async def test_panel_session_project_wins_over_campaign(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    bolag_id = await bolag_demo_customer_id(session)
    projekt = await _add_project(session, bolag_id, "project-wins")
    campaign = await _add_campaign(session, os_id, "OS campaign")
    await _add_panel(
        session,
        "ps_both",
        project_id=projekt.id,
        campaign_id=campaign.id,
    )

    resolved = await customer_id_for_panel_session(session, "ps_both")
    assert resolved == bolag_id


@pytest.mark.asyncio
async def test_panel_session_falls_back_to_campaign_customer(session: AsyncSession):
    bolag_id = await bolag_demo_customer_id(session)
    campaign = await _add_campaign(session, bolag_id, "DD only")
    await _add_panel(session, "ps_campaign_only", campaign_id=campaign.id)

    resolved = await customer_id_for_panel_session(session, "ps_campaign_only")
    assert resolved == bolag_id


@pytest.mark.asyncio
async def test_panel_session_without_scope_uses_os_default(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    await _add_panel(session, "ps_unscoped")

    resolved = await customer_id_for_panel_session(session, "ps_unscoped")
    assert resolved == os_id


@pytest.mark.asyncio
async def test_panel_session_job_uses_project_customer(session: AsyncSession):
    bolag_id = await bolag_demo_customer_id(session)
    projekt = await _add_project(session, bolag_id, "job-scope")
    await _add_panel(session, "ps_job", project_id=projekt.id)

    resolved = await customer_id_for_new_job(
        session,
        JobCreate(kind="panel_session_run", request={"session_id": "ps_job"}),
    )
    assert resolved == bolag_id
