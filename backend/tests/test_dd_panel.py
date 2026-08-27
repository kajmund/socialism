"""Tests for dd_panel protocol and source attribution."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer
from app.services import jobs as jobs_service
from app.services.dd.source_attribution import resolve_source_badge
from app.services.dd.schemas import DdCandidateCompany


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


def test_resolve_source_badge_llm_when_no_external_hits(monkeypatch):
    monkeypatch.setattr("app.services.dd.source_attribution.search_manual", lambda *_a, **_k: [])
    monkeypatch.setattr("app.services.dd.source_attribution.search_duckduckgo", lambda *_a, **_k: [])
    badge = resolve_source_badge(
        sub_question_label="Finansiell hälsa",
        candidate_name="Test AB",
    )
    assert badge.kind == "llm"
    assert badge.label == "Modellbedömning"


@pytest.mark.asyncio
async def test_dd_panel_session_from_campaign(client: AsyncClient, mock_dd_panel_llm, monkeypatch):
    monkeypatch.setattr(
        "app.services.dd.source_attribution.search_duckduckgo",
        lambda *_a, **_k: [],
    )

    create = await client.post(
        "/dd/campaigns",
        json={"title": "Panel DD", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
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
    body = session_resp.json()
    assert body["protocol"] == "dd_panel"
    assert body["config"]["candidate"]["id"] == candidate_id
    assert len(body["config"]["expert_slots"]) == 4

    session_id = body["id"]
    done = asyncio.Event()

    def _schedule(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule)

    run = await client.post(f"/panel/sessions/{session_id}/run")
    assert run.status_code == 202
    await asyncio.wait_for(done.wait(), timeout=15)

    session = await client.get(f"/panel/sessions/{session_id}")
    assert session.status_code == 200
    finished = session.json()
    assert finished["status"] == "succeeded"
    assert finished["result"] is not None
    assert len(finished["result"]["scores"]) == 16
    assert finished["result"]["summary"]
    assert any(t["phase"] == "score" for t in finished["transcript"])

    jobs_service.set_schedule_hook(None)


def test_candidate_brief_format():
    from app.services.panel.dd_engine import _candidate_brief

    text = _candidate_brief(
        DdCandidateCompany(
            id="c1",
            namn="Test AB",
            organisationsnummer="556000-0000",
            alder_ar=12,
            omrade="Stockholm",
            resultat="vinst",
            omsattning_sek=1_000_000,
            anstallda=25,
            beskrivning="Nischad SaaS-leverantör.",
        )
    )
    assert "Test AB" in text
    assert "Nischad SaaS" in text
