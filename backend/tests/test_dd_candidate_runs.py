"""Tests for dd_candidate_runs persistence."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from app.database.models import DdCampaign, PanelSession, Report
from app.llm import set_text_completer
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.dd.candidate_runs import get_candidate_run, upsert_panel_session, upsert_report
from app.services.kund_store import bolag_demo_customer_id


@pytest.fixture
def mock_dd_panel_llm():
    score_counter = {"n": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "Första raden: JA eller NEJ" in user or "First line: YES or NO" in user:
            return "JA"
        if "Ingen av experterna" in user or "None of the experts" in user:
            return "Panelen saknar rätt kompetens för frågan."
        if "ENDAST med JSON" in user or "ONLY with JSON" in user:
            score_counter["n"] += 1
            score = 5 + (score_counter["n"] % 4)
            return json.dumps({"score": score, "motivation": f"Bedömning {score_counter['n']}"})
        if "Poängtabell" in user or "Score table" in user:
            return "Sammanfattning: blandad bild med tydlig dissensus kring legal risk."
        if "Nuvarande delfråga" in user or "Current sub-question" in user:
            return "Vi går vidare till nästa delfråga."
        if "Öppna panelen" in user or "Open briefly" in user:
            return "Välkommen till DD-panelen."
        return "OK"

    set_text_completer(_complete)
    yield
    set_text_completer(None)


@pytest.mark.asyncio
async def test_candidate_run_links_panel_and_report(
    client: AsyncClient,
    mock_dd_panel_llm,
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    create = await client.post(
        "/dd/campaigns",
        json={"title": "Runs link", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    assert create.status_code == 201
    campaign_id = create.json()["id"]

    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert sourced.status_code == 200
    candidate_id = sourced.json()["candidates"][0]["id"]

    session_resp = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": candidate_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    got = await client.get(f"/dd/campaigns/{campaign_id}")
    assert got.status_code == 200
    runs = got.json()["candidate_runs"]
    assert len(runs) == 1
    assert runs[0]["candidate_id"] == candidate_id
    assert runs[0]["panel_session_id"] == session_id
    assert runs[0]["report_id"] is None

    panel_done = asyncio.Event()

    def _schedule_panel(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            panel_done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule_panel)
    run_panel = await client.post(f"/panel/sessions/{session_id}/run")
    assert run_panel.status_code == 202
    await asyncio.wait_for(panel_done.wait(), timeout=20)

    report_done = asyncio.Event()

    def _schedule_report(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            report_done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule_report)
    create_report = await client.post(
        "/reports",
        json={
            "sources": [
                {
                    "type": "dd_session",
                    "session_id": session_id,
                    "candidate_id": candidate_id,
                }
            ],
            "title": "Linked DD report",
        },
    )
    assert create_report.status_code == 202, create_report.text
    report_id = create_report.json()["id"]
    await asyncio.wait_for(report_done.wait(), timeout=20)
    jobs_service.set_schedule_hook(None)

    linked = await client.get(f"/dd/campaigns/{campaign_id}")
    assert linked.status_code == 200
    runs = linked.json()["candidate_runs"]
    assert len(runs) == 1
    assert runs[0]["panel_session_id"] == session_id
    assert runs[0]["report_id"] == report_id

    session_resp_2 = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": candidate_id},
    )
    assert session_resp_2.status_code == 201
    new_session_id = session_resp_2.json()["id"]
    assert new_session_id != session_id

    after_rerun = await client.get(f"/dd/campaigns/{campaign_id}")
    assert after_rerun.status_code == 200
    runs = after_rerun.json()["candidate_runs"]
    assert len(runs) == 1
    assert runs[0]["panel_session_id"] == new_session_id
    assert runs[0]["report_id"] is None

    panel_done_2 = asyncio.Event()

    def _schedule_panel_2(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            panel_done_2.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule_panel_2)
    rerun_panel = await client.post(f"/panel/sessions/{new_session_id}/run")
    assert rerun_panel.status_code == 202
    await asyncio.wait_for(panel_done_2.wait(), timeout=20)

    report_done_2 = asyncio.Event()

    def _schedule_report_2(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            report_done_2.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule_report_2)
    replace_report = await client.post(
        "/reports",
        json={
            "sources": [
                {
                    "type": "dd_session",
                    "session_id": new_session_id,
                    "candidate_id": candidate_id,
                }
            ],
            "title": "Linked DD report",
        },
    )
    assert replace_report.status_code == 202, replace_report.text
    new_report_id = replace_report.json()["id"]
    await asyncio.wait_for(report_done_2.wait(), timeout=20)
    jobs_service.set_schedule_hook(None)

    replaced = await client.get(f"/reports/{new_report_id}")
    assert replaced.status_code == 200
    assert replaced.json()["sources"][0]["session_id"] == new_session_id

    linked_again = await client.get(f"/dd/campaigns/{campaign_id}")
    assert linked_again.json()["candidate_runs"][0]["report_id"] == new_report_id

    listed = await client.get("/dd/campaigns?module=dd")
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item["id"] == campaign_id)
    assert row["candidate_runs"] == []

    deleted = await client.delete(f"/dd/campaigns/{campaign_id}/runs/{candidate_id}")
    assert deleted.status_code == 204
    after_delete = await client.get(f"/dd/campaigns/{campaign_id}")
    assert after_delete.json()["candidate_runs"] == []
    missing = await client.delete(f"/dd/campaigns/{campaign_id}/runs/{candidate_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_candidate_run_upserts_merge_links(client_db):
    """Parallel panel/report upserts must not 500 or drop links on unique constraint races."""
    client, factory = client_db

    create = await client.post(
        "/dd/campaigns",
        json={"title": "Race test", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    assert create.status_code == 201
    campaign_id = create.json()["id"]
    candidate_id = "race_candidate_1"

    async with factory() as session:
        campaign = await session.get(DdCampaign, campaign_id)
        assert campaign is not None
        campaign.candidates = [
            {
                "id": candidate_id,
                "namn": "Race AB",
                "organisationsnummer": "556999-9999",
                "alder_ar": 12,
                "omrade": "Test",
                "resultat": "vinst",
                "omsattning_sek": 1_000_000,
                "anstallda": 3,
                "beskrivning": "Test",
            }
        ]
        bolag_id = await bolag_demo_customer_id(session)
        session.add(
            PanelSession(
                id="panel_race",
                protocol="dd_panel",
                status="draft",
                config={"protocol": "dd_panel", "topic": "t", "expert_slots": [{"slot_id": "a", "label": "A"}]},
                transcript=[],
                scratchpads={},
                campaign_id=campaign_id,
            )
        )
        session.add(
            Report(
                id="rpt_race",
                customer_id=bolag_id,
                status="pending",
                title="Race report",
                locale="sv",
                mode="dd",
                sources=[],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        await session.commit()

    async def _upsert_panel() -> None:
        async with factory() as session:
            await upsert_panel_session(
                session,
                campaign_id=campaign_id,
                candidate_id=candidate_id,
                panel_session_id="panel_race",
            )
            await session.commit()

    async def _upsert_report() -> None:
        async with factory() as session:
            await upsert_report(
                session,
                campaign_id=campaign_id,
                candidate_id=candidate_id,
                report_id="rpt_race",
            )
            await session.commit()

    await asyncio.gather(_upsert_panel(), _upsert_report())

    async with factory() as session:
        row = await get_candidate_run(
            session,
            campaign_id=campaign_id,
            candidate_id=candidate_id,
        )
        assert row is not None
        assert row.panel_session_id == "panel_race"
        assert row.report_id == "rpt_race"


@pytest.mark.asyncio
async def test_stale_dd_report_does_not_relink_after_rerun(client_db):
    """Report create for a superseded panel session must not overwrite the current run link."""
    client, factory = client_db

    create = await client.post(
        "/dd/campaigns",
        json={"title": "Stale report", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    assert create.status_code == 201
    campaign_id = create.json()["id"]
    candidate_id = "stale_candidate_1"
    session_a = "panel_stale_a"
    session_b = "panel_stale_b"

    async with factory() as session:
        campaign = await session.get(DdCampaign, campaign_id)
        assert campaign is not None
        candidate = {
            "id": candidate_id,
            "namn": "Stale AB",
            "organisationsnummer": "556111-2222",
            "alder_ar": 10,
            "omrade": "Test",
            "resultat": "vinst",
            "omsattning_sek": 1_000_000,
            "anstallda": 3,
            "beskrivning": "Test",
        }
        campaign.candidates = [candidate]
        bolag_id = await bolag_demo_customer_id(session)
        result_payload = {
            "candidate": candidate,
            "scores": [],
            "dissensus": [],
            "unanswered": [],
            "summary": "Test summary",
        }
        session.add(
            PanelSession(
                id=session_a,
                protocol="dd_panel",
                status="succeeded",
                config={"protocol": "dd_panel", "topic": "t", "expert_slots": [{"slot_id": "a", "label": "A"}]},
                transcript=[],
                scratchpads={},
                result=result_payload,
                campaign_id=campaign_id,
            )
        )
        session.add(
            PanelSession(
                id=session_b,
                protocol="dd_panel",
                status="running",
                config={"protocol": "dd_panel", "topic": "t", "expert_slots": [{"slot_id": "a", "label": "A"}]},
                transcript=[],
                scratchpads={},
                campaign_id=campaign_id,
            )
        )
        session.add(
            Report(
                id="rpt_stale_old",
                customer_id=bolag_id,
                status="succeeded",
                title="Old report",
                locale="sv",
                mode="dd",
                sources=[
                    {
                        "type": "dd_session",
                        "session_id": session_a,
                        "candidate_id": candidate_id,
                        "label": "Stale AB",
                    }
                ],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        await session.commit()

    async with factory() as session:
        await upsert_panel_session(
            session,
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            panel_session_id=session_a,
        )
        await upsert_report(
            session,
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            report_id="rpt_stale_old",
        )
        await upsert_panel_session(
            session,
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            panel_session_id=session_b,
        )
        await session.commit()

    after_rerun = await client.get(f"/dd/campaigns/{campaign_id}")
    run = after_rerun.json()["candidate_runs"][0]
    assert run["panel_session_id"] == session_b
    assert run["report_id"] is None

    jobs_service.set_schedule_hook(lambda _job_id: None)
    stale = await client.post(
        "/reports",
        json={
            "sources": [
                {
                    "type": "dd_session",
                    "session_id": session_a,
                    "candidate_id": candidate_id,
                }
            ],
            "title": "Stale session report",
        },
    )
    assert stale.status_code == 202, stale.text

    linked = await client.get(f"/dd/campaigns/{campaign_id}")
    run = linked.json()["candidate_runs"][0]
    assert run["panel_session_id"] == session_b
    assert run["report_id"] is None
