"""Tests for dd_panel protocol and source attribution."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer, set_tools_completer
from app.services import jobs as jobs_service
from app.services.dd.schemas import DdAccountYear, DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge, resolve_source_badge


@pytest.fixture
def mock_dd_panel_llm():
    score_counter = {"n": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "Första raden: JA eller NEJ" in user or "First line: YES or NO" in user:
            return "JA\nDelfrågan är min kärnkompetens."
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

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)
    yield
    set_text_completer(None)
    set_tools_completer(None)


def test_resolve_source_badge_llm_when_no_figures_and_no_web():
    badge = resolve_source_badge()
    assert badge.kind == "llm"
    assert badge.label == "Modellbedömning"


def test_resolve_source_badge_grunddata_for_any_sub_question_when_figures_in_brief():
    badge = resolve_source_badge(figures_in_brief=True)
    assert badge.label == "Grunddata"
    assert badge.kind == "llm"
    assert badge.detail == "Nyckeltal från kandidatunderlaget"


def test_resolve_source_badge_grunddata_wins_over_web_detail():
    badge = resolve_source_badge(
        figures_in_brief=True,
        web_detail="Crowd Collective Finland AB i Linköping - Merinfo.se",
    )
    assert badge.label == "Grunddata"
    assert "Merinfo" not in badge.detail


def test_resolve_source_badge_web_only_without_figures():
    badge = resolve_source_badge(
        figures_in_brief=False,
        web_detail="Bolagsverket",
    )
    assert badge.kind == "web"
    assert badge.label == "Webb"
    assert badge.detail == "Bolagsverket"


def test_source_badge_drops_stored_okf():
    badge = SourceBadge.model_validate(
        {"kind": "okf", "label": "OKF-manual", "detail": "Köra en DD-kampanj"}
    )
    assert badge.kind == "llm"
    assert badge.label == "Modellbedömning"


@pytest.mark.asyncio
async def test_dd_panel_session_from_campaign(client: AsyncClient, mock_dd_panel_llm):
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
    assert finished["result"]["unanswered"] == []
    assert finished["result"]["summary"]
    assert any(t["phase"] == "raise_hand" for t in finished["transcript"])
    assert any(
        t["phase"] == "raise_hand" and "kärnkompetens" in t["content"]
        for t in finished["transcript"]
    )
    assert any(t["phase"] == "score" for t in finished["transcript"])

    jobs_service.set_schedule_hook(None)


def test_parse_score_payload_skips_invalid_object_and_reads_score():
    from app.services.panel.structured_scoring import _parse_score_payload

    score, motivation = _parse_score_payload(
        'Bolaget: {"orgnr": "556703-7485"}\n\n'
        '{"score": 8, "motivation": "Stabil kassa"}'
    )
    assert score == 8
    assert "Stabil" in motivation


def test_parse_score_payload_rejects_non_numeric_score():
    from app.services.panel.structured_scoring import _parse_score_payload

    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_score_payload('{"score": insert, "motivation": "väntar på uppslag"}')


@pytest.mark.asyncio
async def test_expert_score_asks_for_json_after_invalid_tool_reply():
    from app.llm import set_text_completer, set_tools_completer
    from app.services.dd.source_attribution import SourceBadge
    from app.services.dd.sub_questions import DD_SUB_QUESTION_DEFAULTS, SubQuestionRef
    from app.services.panel.structured_scoring import _expert_score
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
            SubQuestionRef(id=DD_SUB_QUESTION_DEFAULTS[0].key, label=DD_SUB_QUESTION_DEFAULTS[0].label),
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
    from app.services.panel.structured_scoring import _candidate_brief

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
    assert "1 000 000 SEK" in text


def test_candidate_has_figures_from_accounts():
    from app.services.panel.structured_scoring import _candidate_has_figures

    empty = DdCandidateCompany(
        id="c1",
        namn="Tom AB",
        organisationsnummer="556000-0000",
        alder_ar=1,
        omrade="Stockholm",
        resultat="oavsett",
    )
    with_year = empty.model_copy(
        update={
            "rakenskaper": [
                DdAccountYear(year="2024", omsattning_sek=2_000_000),
            ]
        }
    )
    assert _candidate_has_figures(empty) is False
    assert _candidate_has_figures(with_year) is True


@pytest.mark.asyncio
async def test_expert_raise_hand_dd_accepts_ja_and_yes():
    from app.llm import set_text_completer
    from app.services.dd.sub_questions import DD_SUB_QUESTION_DEFAULTS, SubQuestionRef
    from app.services.panel.structured_scoring import _expert_raise_hand_dd
    from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
    from app.services.prompt_catalog import default_prompts

    replies = iter(["ja, det kan jag", "Yes — within my brief", "nej"])

    async def _complete(_messages, *, model=None):
        return next(replies)

    set_text_completer(_complete)
    try:
        slot = PanelExpertSlot(slot_id="fin", label="Finans", profile="Siffror")
        config = PanelSessionConfig(
            topic="Spotify AB",
            brief="Spotify AB",
            expert_slots=[slot],
        )
        prompts = default_prompts("sv")
        wants_fin, text_fin = await _expert_raise_hand_dd(
            slot, config, SubQuestionRef(id=DD_SUB_QUESTION_DEFAULTS[0].key, label=DD_SUB_QUESTION_DEFAULTS[0].label), prompts
        )
        wants_legal, text_legal = await _expert_raise_hand_dd(
            slot, config, SubQuestionRef(id=DD_SUB_QUESTION_DEFAULTS[1].key, label=DD_SUB_QUESTION_DEFAULTS[1].label), prompts
        )
        wants_market, text_market = await _expert_raise_hand_dd(
            slot, config, SubQuestionRef(id=DD_SUB_QUESTION_DEFAULTS[2].key, label=DD_SUB_QUESTION_DEFAULTS[2].label), prompts
        )
        assert wants_fin and "ja" in text_fin.lower()
        assert wants_legal and "yes" in text_legal.lower()
        assert not wants_market and "nej" in text_market.lower()
    finally:
        set_text_completer(None)


@pytest.mark.asyncio
async def test_dd_panel_skips_score_when_no_expert_raises_hand(
    client: AsyncClient,
):
    from app.services.dd.sub_questions import DD_SUB_QUESTION_DEFAULTS, SubQuestionRef

    score_counter = {"n": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "Första raden: JA eller NEJ" in user or "First line: YES or NO" in user:
            if "Legal risk" in user:
                return "NEJ\nLegal risk är inte min kärnkompetens."
            return "JA\nDelfrågan är min kärnkompetens."
        if "Ingen av experterna" in user or "None of the experts" in user:
            return "Legal risk kräver en jurist som saknas i den här panelen."
        if "ENDAST med JSON" in user or "ONLY with JSON" in user:
            score_counter["n"] += 1
            return json.dumps(
                {"score": 6, "motivation": f"Bedömning {score_counter['n']}"}
            )
        if "Poängtabell" in user or "Score table" in user:
            return "Sammanfattning med täckningslucka kring legal risk."
        if "Nuvarande delfråga" in user or "Current sub-question" in user:
            return "Vi går vidare till nästa delfråga."
        if "Öppna panelen" in user or "Open briefly" in user:
            return "Välkommen till DD-panelen."
        return "OK"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)
    try:
        create = await client.post(
            "/dd/campaigns",
            json={
                "title": "Raise-hand DD",
                "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""},
            },
        )
        campaign_id = create.json()["id"]
        sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
        candidate_id = sourced.json()["candidates"][0]["id"]
        session_resp = await client.post(
            f"/dd/campaigns/{campaign_id}/panel-sessions",
            json={"campaign_id": campaign_id, "candidate_id": candidate_id},
        )
        session_id = session_resp.json()["id"]
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
        jobs_service.set_schedule_hook(None)

        session = await client.get(f"/panel/sessions/{session_id}")
        finished = session.json()
        assert finished["status"] == "succeeded"
        unanswered = finished["result"]["unanswered"]
        assert len(unanswered) == 1
        assert unanswered[0]["sub_question_id"] == "legal_risk"
        assert "jurist" in unanswered[0]["moderator_note"].lower()
        scored_ids = {row["sub_question_id"] for row in finished["result"]["scores"]}
        assert "legal_risk" not in scored_ids
        assert len(finished["result"]["scores"]) == 12
        assert any(t["phase"] == "unanswered" for t in finished["transcript"])
        assert not any(
            t["phase"] == "score" and t.get("sub_question_id") == "legal_risk"
            for t in finished["transcript"]
        )
        assert {d.key for d in DD_SUB_QUESTION_DEFAULTS} - scored_ids == {"legal_risk"}
    finally:
        set_text_completer(None)
        set_tools_completer(None)


def test_parse_raise_hand_reply_keeps_reason():
    from app.services.panel.structured_scoring import parse_raise_hand_reply

    wants, text = parse_raise_hand_reply(
        "JA\nMarknadsposition är min kärnkompetens — jag bedömer konkurrens och prissättning."
    )
    assert wants is True
    assert "kärnkompetens" in text
    assert parse_raise_hand_reply("NEJ. Jag är jurist, inte marknad.")[0] is False
    assert parse_raise_hand_reply("Yes — within my brief")[0] is True
    assert parse_raise_hand_reply("")[0] is False


def test_transcript_text_skips_raise_hand():
    from app.services.panel.structured_scoring import _transcript_text
    from app.services.panel.schemas import PanelTurn

    text = _transcript_text(
        [
            PanelTurn(turn_id="1", speaker="Spinndoktor", phase="sub_question", content="**Nils Marknad:** 6/10"),
            PanelTurn(turn_id="2", speaker="Daniel (Finans)", phase="raise_hand", content="JA"),
            PanelTurn(turn_id="3", speaker="Lisa (Legal/Skatte)", phase="score", content="Poäng 6/10"),
        ]
    )
    assert "Nils Marknad" not in text
    assert "Poäng 6/10" in text
    assert "JA" not in text


def test_transcript_text_skips_opening_preview():
    from app.services.panel.structured_scoring import _transcript_text
    from app.services.panel.schemas import PanelTurn

    text = _transcript_text(
        [
            PanelTurn(
                turn_id="1",
                speaker="Spinndoktor",
                phase="opening",
                content="Vi tar en delfråga i taget (legal risk, marknadsposition).",
            ),
            PanelTurn(
                turn_id="2",
                speaker="Lisa (Legal/Skatte)",
                phase="score",
                content="Poäng 7/10",
            ),
        ]
    )
    assert "legal risk" not in text
    assert "Poäng 7/10" in text


def test_visible_moderator_text_strips_report_refs():
    from app.services.panel.structured_scoring import _visible_moderator_text

    text = _visible_moderator_text(
        "Vi börjar med era bedömningar — ni har ordet. [[ref:mottagande]]"
    )
    assert "[[ref:mottagande]]" not in text
    assert "ni har ordet" in text


@pytest.mark.asyncio
async def test_dd_moderator_opening_uses_panel_system_and_strips_refs(monkeypatch):
    from app.llm import set_text_completer
    from app.services.panel.structured_scoring import _moderator_opening
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
        text = await _moderator_opening(
            config,
            default_prompts("sv"),
            "Du deltar som Spinndoktor\n\nHitta inte på namn.",
        )
    finally:
        set_text_completer(None)

    assert seen
    assert seen[0][0] == {
        "role": "system",
        "content": "Du deltar som Spinndoktor\n\nHitta inte på namn.",
    }
    assert seen[0][1] == {"role": "system", "content": "Test AB i Stockholm"}
    assert "Test AB i Stockholm" not in seen[0][0]["content"]
    assert "[[ref:mottagande]]" not in text
    assert "DD-panelen" in text
