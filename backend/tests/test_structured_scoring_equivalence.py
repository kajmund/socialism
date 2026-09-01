"""structured_scoring contract (dual-run against dd_engine passed before that file was removed).

Equivalence an agent can pass/fail without comparing transcripts:

1. Same sub-question coverage (every question is scored or unanswered, not both).
2. Dissensus when max−min ≥ 3; flags carry min/max/spread.
3. Unanswered ids and notes when nobody raises a hand.
4. Scores in 1–10 with non-empty motivations and a source badge.
5. Summary present.

Under the mocked completer, scores and notes are deterministic so (4)–(5) are exact.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.llm import set_text_completer, set_tools_completer
from app.services.dd.schemas import DdCandidateCompany
from app.services.dd.sub_questions import DD_SUB_QUESTION_DEFAULTS
from app.services.panel.result import dd_panel_result_from_stored, is_panel_result_envelope
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.structured_scoring import run_structured_scoring
from app.services.prompt_store import require_active_prompts


def _install_dd_mock() -> None:
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


def _dd_config() -> PanelSessionConfig:
    candidate = DdCandidateCompany(
        id="cand_eq",
        namn="Ekvivalens AB",
        organisationsnummer="556677-0001",
        alder_ar=10,
        omrade="Göteborg",
        resultat="vinst",
        omsattning_sek=5_000_000,
        anstallda=20,
        beskrivning="Testbolag för dual-run.",
    )
    return PanelSessionConfig(
        protocol="dd_panel",
        module="dd",
        topic=f"Due diligence: {candidate.namn}",
        brief=(
            f"Namn: {candidate.namn}\n"
            f"Omsättning: {candidate.omsattning_sek}\n"
            f"Anställda: {candidate.anstallda}"
        ),
        expert_slots=[
            PanelExpertSlot(slot_id="fin", label="Finansiell analytiker", profile="Siffror"),
            PanelExpertSlot(slot_id="legal", label="Jurist", profile="Avtal"),
        ],
        candidate=candidate,
        candidate_id=candidate.id,
    )


@pytest.mark.asyncio
async def test_structured_scoring_coverage_dissensus_and_motivations(client_db):
    _client, factory = client_db
    config = _dd_config()
    _install_dd_mock()
    async with factory() as db:
        prompts = await require_active_prompts(db)
        created = await create_panel_session(db, PanelSessionCreate(config=config))
        row = await get_panel_session(db, created.id)
        assert row is not None
        await run_structured_scoring(db, row, prompts)
        await db.commit()
        assert is_panel_result_envelope(row.result or {})
        result = dd_panel_result_from_stored(row.result or {})

    expected = {item.key for item in DD_SUB_QUESTION_DEFAULTS}
    scored = {row.sub_question_id for row in result.scores}
    unanswered = {note.sub_question_id for note in result.unanswered}
    assert scored | unanswered == expected
    assert scored.isdisjoint(unanswered)
    assert unanswered == set()
    assert len(result.scores) == 8
    for row in result.scores:
        assert 1 <= row.score <= 10
        assert row.motivation.strip()
        assert row.source.label
    assert any(note.spread >= 3 for note in result.dissensus)
    assert result.summary.strip()


@pytest.mark.asyncio
async def test_structured_scoring_unanswered_when_no_raise_hand(client_db):
    _client, factory = client_db
    config = _dd_config()
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
            return json.dumps({"score": 6, "motivation": f"Bedömning {score_counter['n']}"})
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

    async with factory() as db:
        prompts = await require_active_prompts(db)
        created = await create_panel_session(db, PanelSessionCreate(config=config))
        row = await get_panel_session(db, created.id)
        assert row is not None
        await run_structured_scoring(db, row, prompts)
        await db.commit()
        result = dd_panel_result_from_stored(row.result or {})

    unanswered_ids = {note.sub_question_id for note in result.unanswered}
    scored_ids = {row.sub_question_id for row in result.scores}
    assert unanswered_ids == {"legal_risk"}
    assert "legal_risk" not in scored_ids
    assert all(note.moderator_note.strip() for note in result.unanswered)


@pytest.mark.asyncio
async def test_structured_scoring_requires_module(client_db):
    _client, factory = client_db
    config = _dd_config()
    config.module = None
    _install_dd_mock()
    async with factory() as db:
        prompts = await require_active_prompts(db)
        created = await create_panel_session(db, PanelSessionCreate(config=config))
        row = await get_panel_session(db, created.id)
        assert row is not None
        with pytest.raises(RuntimeError, match="config.module"):
            await run_structured_scoring(db, row, prompts)
