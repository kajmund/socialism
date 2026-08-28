"""Tests for dd_panel protocol and source attribution."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer, set_tools_completer
from app.services import jobs as jobs_service
from app.services.dd.schemas import DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge, resolve_source_badge


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

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)
    yield
    set_text_completer(None)
    set_tools_completer(None)


def test_resolve_source_badge_llm_when_no_external_hits(monkeypatch):
    def _empty(query: str, number_of_result_pages: int = 5):
        return []

    monkeypatch.setattr("app.services.dd.source_attribution.search_duckduckgo", _empty)
    badge = resolve_source_badge(
        sub_question_label="Finansiell hälsa",
        candidate_name="Test AB",
    )
    assert badge.kind == "llm"
    assert badge.label == "Modellbedömning"


def test_resolve_source_badge_web_uses_search_signature(monkeypatch):
    seen: dict[str, object] = {}

    def _hit(query: str, number_of_result_pages: int = 5):
        seen["query"] = query
        seen["pages"] = number_of_result_pages
        return [{"title": "Bolagsverket", "url": "https://bolagsverket.se"}]

    monkeypatch.setattr("app.services.dd.source_attribution.search_duckduckgo", _hit)
    badge = resolve_source_badge(
        sub_question_label="Finansiell hälsa",
        candidate_name="Test AB",
    )
    assert badge.kind == "web"
    assert badge.label == "Webb"
    assert "Bolagsverket" in badge.detail
    assert seen["pages"] == 1
    assert "Test AB" in str(seen["query"])


def test_source_badge_drops_stored_okf():
    badge = SourceBadge.model_validate(
        {"kind": "okf", "label": "OKF-manual", "detail": "Köra en DD-kampanj"}
    )
    assert badge.kind == "llm"
    assert badge.label == "Modellbedömning"


@pytest.mark.asyncio
async def test_dd_panel_session_from_campaign(client: AsyncClient, mock_dd_panel_llm, monkeypatch):
    monkeypatch.setattr(
        "app.services.dd.source_attribution.search_duckduckgo",
        lambda query, number_of_result_pages=5: [],
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


def test_parse_score_payload_skips_invalid_object_and_reads_score():
    from app.services.panel.dd_engine import _parse_score_payload

    score, motivation = _parse_score_payload(
        'Bolaget: {"orgnr": "556703-7485"}\n\n'
        '{"score": 8, "motivation": "Stabil kassa"}'
    )
    assert score == 8
    assert "Stabil" in motivation


def test_parse_score_payload_rejects_non_numeric_score():
    from app.services.panel.dd_engine import _parse_score_payload

    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_score_payload('{"score": insert, "motivation": "väntar på uppslag"}')


@pytest.mark.asyncio
async def test_expert_score_asks_for_json_after_invalid_tool_reply():
    from app.llm import set_text_completer, set_tools_completer
    from app.services.dd.source_attribution import SourceBadge
    from app.services.dd.sub_questions import DD_SUB_QUESTIONS
    from app.services.panel.dd_engine import _expert_score
    from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
    from app.services.prompt_catalog import default_prompts

    async def _tools(_messages, tools=None):
        return SimpleNamespace(
            content='{"score": insert, "motivation": "väntar"}',
            tool_calls=None,
        )

    async def _complete(_messages, *, model=None):
        return json.dumps({"score": 6, "motivation": "Efter uppslag: ok kassa"})

    set_tools_completer(_tools)
    set_text_completer(_complete)
    try:
        score, motivation = await _expert_score(
            PanelExpertSlot(slot_id="fin", label="Finans", profile="Siffror"),
            PanelSessionConfig(
                topic="Spotify AB",
                brief="Spotify AB",
                expert_slots=[
                    PanelExpertSlot(slot_id="fin", label="Finans", profile="Siffror")
                ],
            ),
            DD_SUB_QUESTIONS[0],
            SourceBadge(kind="llm", label="Modellbedömning", detail=""),
            [],
            default_prompts("sv"),
        )
    finally:
        set_tools_completer(None)
        set_text_completer(None)

    assert score == 6
    assert "kassa" in motivation


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


def test_visible_moderator_text_strips_report_refs():
    from app.services.panel.dd_engine import _visible_moderator_text

    text = _visible_moderator_text(
        "Vi börjar med era bedömningar — ni har ordet. [[ref:mottagande]]"
    )
    assert "[[ref:mottagande]]" not in text
    assert "ni har ordet" in text


@pytest.mark.asyncio
async def test_dd_moderator_opening_uses_panel_system_and_strips_refs(monkeypatch):
    from app.llm import set_text_completer
    from app.services.panel.dd_engine import _moderator_opening
    from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
    from app.services.prompt_catalog import default_prompts

    seen: list[list[dict[str, str]]] = []

    async def _complete(messages, *, model=None):
        seen.append(messages)
        return "Välkommen till DD-panelen. [[ref:mottagande]]"

    set_text_completer(_complete)
    try:
        config = PanelSessionConfig(
            protocol="dd_panel",
            topic="Test AB",
            brief="Test AB i Stockholm",
            expert_slots=[PanelExpertSlot(slot_id="e1", label="Finans")],
            candidate=DdCandidateCompany(
                id="c1",
                namn="Test AB",
                organisationsnummer="556000-0000",
                alder_ar=12,
                omrade="Stockholm",
                resultat="vinst",
            ),
        )
        text = await _moderator_opening(config, default_prompts("sv"))
    finally:
        set_text_completer(None)

    assert seen
    assert "expertpanel" in seen[0][0]["content"]
    assert "[[ref:id]]" not in seen[0][0]["content"]
    assert "[[ref:mottagande]]" not in text
    assert "DD-panelen" in text
