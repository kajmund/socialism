"""Tests for dd_candidate_runs persistence."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer
from app.services import jobs as jobs_service


@pytest.fixture
def mock_dd_panel_llm():
    score_counter = {"n": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
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
    monkeypatch.setattr(
        "app.services.dd.source_attribution.search_duckduckgo",
        lambda *_a, **_k: [],
    )
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

    listed = await client.get("/dd/campaigns?module=dd")
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item["id"] == campaign_id)
    assert row["candidate_runs"] == []
