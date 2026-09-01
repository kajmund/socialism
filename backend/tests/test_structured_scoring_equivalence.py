"""Dual-run: legacy dd_engine vs new structured_scoring.

Under a live LLM the two methods cannot be bit-identical. Equivalence for an
agent (no manual transcript compare) is:

1. Same sub-question coverage (every question is scored or unanswered, not both).
2. Same dissensus flags (same sub_question_ids, same min/max/spread).
3. Same unanswered ids and notes.
4. Same expert×question scores, motivations, and source badges.
5. Same summary text.

This test uses the shared mocked completer so (4)–(5) are exact. If a future
change makes LLM order diverge, keep (1)–(3) as the hard floor and fail loud
on score identity so the agent sees a concrete assertion, not a compile-only pass.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.llm import set_text_completer, set_tools_completer
from app.services.dd.schemas import DdCandidateCompany
from app.services.panel.dd_engine import run_dd_panel
from app.services.panel.result import dd_panel_result_from_stored, is_panel_result_envelope
from app.services.panel.schemas import (
    DdPanelResult,
    PanelExpertSlot,
    PanelSessionConfig,
    PanelSessionCreate,
)
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


def assert_dd_results_equivalent(legacy: DdPanelResult, new: DdPanelResult) -> None:
    scored_l = {row.sub_question_id for row in legacy.scores}
    scored_n = {row.sub_question_id for row in new.scores}
    unanswered_l = {note.sub_question_id for note in legacy.unanswered}
    unanswered_n = {note.sub_question_id for note in new.unanswered}
    assert scored_l == scored_n
    assert unanswered_l == unanswered_n
    assert scored_l.isdisjoint(unanswered_l)
    assert scored_l | unanswered_l

    def score_key(row):
        return (
            row.expert_slot_id,
            row.sub_question_id,
            row.score,
            row.motivation,
            row.source.kind,
            row.source.label,
            row.source.detail,
        )

    assert sorted(score_key(row) for row in legacy.scores) == sorted(
        score_key(row) for row in new.scores
    )

    def dissensus_key(note):
        return (note.sub_question_id, note.min_score, note.max_score, note.spread)

    assert sorted(dissensus_key(n) for n in legacy.dissensus) == sorted(
        dissensus_key(n) for n in new.dissensus
    )

    def unanswered_key(note):
        return (note.sub_question_id, note.moderator_note)

    assert sorted(unanswered_key(n) for n in legacy.unanswered) == sorted(
        unanswered_key(n) for n in new.unanswered
    )
    assert legacy.summary == new.summary


@pytest.mark.asyncio
async def test_structured_scoring_matches_legacy_dd_engine(client_db):
    _client, factory = client_db
    config = _dd_config()

    async with factory() as db:
        prompts = await require_active_prompts(db)
        legacy_out = await create_panel_session(db, PanelSessionCreate(config=config))
        new_out = await create_panel_session(db, PanelSessionCreate(config=config))
        await db.commit()

    _install_dd_mock()
    async with factory() as db:
        prompts = await require_active_prompts(db)
        legacy_row = await get_panel_session(db, legacy_out.id)
        assert legacy_row is not None
        await run_dd_panel(db, legacy_row, prompts)
        await db.commit()
        legacy_result = DdPanelResult.model_validate(legacy_row.result)

    _install_dd_mock()
    async with factory() as db:
        prompts = await require_active_prompts(db)
        new_row = await get_panel_session(db, new_out.id)
        assert new_row is not None
        await run_structured_scoring(db, new_row, prompts)
        await db.commit()
        assert is_panel_result_envelope(new_row.result or {})
        new_result = dd_panel_result_from_stored(new_row.result or {})

    assert_dd_results_equivalent(legacy_result, new_result)
    assert len(legacy_result.scores) == 8
    assert legacy_result.unanswered == []
    assert any(note.spread >= 3 for note in legacy_result.dissensus)


@pytest.mark.asyncio
async def test_structured_scoring_matches_legacy_unanswered_path(client_db):
    _client, factory = client_db
    config = _dd_config()

    async def _install_skip_legal() -> None:
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

    async with factory() as db:
        prompts = await require_active_prompts(db)
        legacy_out = await create_panel_session(db, PanelSessionCreate(config=config))
        new_out = await create_panel_session(db, PanelSessionCreate(config=config))
        await db.commit()

    await _install_skip_legal()
    async with factory() as db:
        prompts = await require_active_prompts(db)
        legacy_row = await get_panel_session(db, legacy_out.id)
        assert legacy_row is not None
        await run_dd_panel(db, legacy_row, prompts)
        await db.commit()
        legacy_result = DdPanelResult.model_validate(legacy_row.result)

    await _install_skip_legal()
    async with factory() as db:
        prompts = await require_active_prompts(db)
        new_row = await get_panel_session(db, new_out.id)
        assert new_row is not None
        await run_structured_scoring(db, new_row, prompts)
        await db.commit()
        new_result = dd_panel_result_from_stored(new_row.result or {})

    assert_dd_results_equivalent(legacy_result, new_result)
    unanswered_ids = {note.sub_question_id for note in legacy_result.unanswered}
    assert unanswered_ids == {"legal_risk"}
    scored_ids = {row.sub_question_id for row in legacy_result.scores}
    assert "legal_risk" not in scored_ids


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
