"""Cross-tenant enforcement: user cannot fetch another kund's resources by id."""

from __future__ import annotations

import pytest

from app.database.models import DdCampaign, Job, Report
from app.serializers import utcnow
from tests.conftest import TEST_CUSTOMER_ID, mint_access_token, USER_USER_ID


@pytest.mark.asyncio
async def test_user_cannot_get_other_kund_campaign(client_db, user_client) -> None:
    _client, session_factory = client_db
    async with session_factory() as session:
        campaign = DdCampaign(
            title="Other kund campaign",
            module="dd",
            customer_id=2,  # bolag-demo after ensure_default_kunder
            status="draft",
        )
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)
        campaign_id = campaign.id

    response = await user_client.get(f"/dd/campaigns/{campaign_id}")
    assert response.status_code == 403
    assert response.json()["detail"] == "kund_access_denied"


@pytest.mark.asyncio
async def test_user_cannot_get_other_kund_report(client_db, user_client) -> None:
    _client, session_factory = client_db
    async with session_factory() as session:
        report = Report(
            id="rpt-other-kund",
            title="Other",
            status="succeeded",
            mode="quick",
            locale="sv",
            customer_id=2,
            sources=[],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(report)
        await session.commit()

    response = await user_client.get("/reports/rpt-other-kund")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_create_job_for_other_kund_run(client_db, user_client) -> None:
    _client, session_factory = client_db
    from sqlalchemy import func, select

    from app.database.models import Job, Population, Projekt, Run
    from app.serializers import utcnow
    from app.services.kund_store import bolag_demo_customer_id

    async with session_factory() as session:
        bolag_id = await bolag_demo_customer_id(session)
        projekt = Projekt(
            customer_id=bolag_id,
            name="Bolag proj",
            slug="bolag-proj-scope",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(projekt)
        await session.flush()
        pop = Population(name="BolagPop", size=0, versions=1, fingerprint=[], recipe={})
        session.add(pop)
        await session.flush()
        run = Run(
            project_id=projekt.id,
            name="BolagRun",
            status="draft",
            population_id=pop.id,
            seed="",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id
        before = (await session.execute(select(func.count()).select_from(Job))).scalar_one()

    response = await user_client.post(
        "/jobs",
        json={"kind": "run_simulate", "request": {"run_id": run_id}},
    )
    assert response.status_code == 403

    async with session_factory() as session:
        after = (await session.execute(select(func.count()).select_from(Job))).scalar_one()
    assert after == before


@pytest.mark.asyncio
async def test_user_cannot_get_other_kund_job(client_db, user_client) -> None:
    _client, session_factory = client_db
    async with session_factory() as session:
        job = Job(
            id="job-other-kund",
            kind="run_simulate",
            status="succeeded",
            request={},
            customer_id=2,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(job)
        await session.commit()

    response = await user_client.get("/jobs/job-other-kund")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_can_list_own_kund_only(client_db, user_client) -> None:
    _client, session_factory = client_db
    async with session_factory() as session:
        session.add(
            DdCampaign(
                title="Devbrains campaign",
                module="dd",
                customer_id=TEST_CUSTOMER_ID,
                status="draft",
            )
        )
        session.add(
            DdCampaign(
                title="Bolag campaign",
                module="dd",
                customer_id=2,
                status="draft",
            )
        )
        await session.commit()

    response = await user_client.get("/dd/campaigns")
    assert response.status_code == 200
    titles = {row["title"] for row in response.json()}
    assert "Devbrains campaign" in titles
    assert "Bolag campaign" not in titles


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(client) -> None:
    client.headers.pop("Authorization", None)
    response = await client.get("/jobs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_remains_open(client) -> None:
    client.headers.pop("Authorization", None)
    response = await client.get("/health")
    assert response.status_code == 200
