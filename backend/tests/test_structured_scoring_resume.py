"""Crash/resume for structured_scoring must reuse committed scores and gaps."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.llm import set_text_completer, set_tools_completer
from app.services.dd.schemas import DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge
from app.services.dd.sub_questions import SubQuestionRef
from app.services.kund_store import default_os_customer_id
from app.services.panel.result import dd_panel_result_from_stored
from app.services.panel.schemas import (
    PanelExpertSlot,
    PanelSessionConfig,
    PanelSessionCreate,
    PanelTurn,
)
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.structured_scoring import (
    format_score_turn,
    run_structured_scoring,
    score_from_committed_turn,
    unanswered_from_committed_turn,
)
from app.services.prompt_store import require_active_prompts


def _config() -> PanelSessionConfig:
    candidate = DdCandidateCompany(
        id="cand_resume",
        namn="Resume AB",
        organisationsnummer="556677-0002",
        alder_ar=8,
        omrade="Malmö",
        resultat="vinst",
        omsattning_sek=3_000_000,
        anstallda=12,
        beskrivning="Testbolag för resume.",
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


def _score_turns(transcript: list[dict]) -> list[dict]:
    return [row for row in transcript if row["phase"] == "score"]


def _unanswered_turns(transcript: list[dict]) -> list[dict]:
    return [row for row in transcript if row["phase"] == "unanswered"]


def test_score_turn_roundtrip_is_exact():
    source = SourceBadge(
        kind="llm",
        label="Grunddata",
        detail="Nyckeltal från kandidatunderlaget",
    )
    text = format_score_turn(7, "Committad bedömning.", source)
    turn = PanelTurn(
        turn_id="turn_score",
        speaker="Finansiell analytiker",
        phase="score",
        content=text,
        round_index=1,
        slot_id="fin",
        sub_question_id="finansiell_halsa",
    )
    rebuilt = score_from_committed_turn(
        turn,
        slot=PanelExpertSlot(slot_id="fin", label="Finansiell analytiker"),
        sub_question=SubQuestionRef(id="finansiell_halsa", label="Finansiell hälsa"),
    )
    assert rebuilt.score == 7
    assert rebuilt.motivation == "Committad bedömning."
    assert rebuilt.source == source
    assert format_score_turn(rebuilt.score, rebuilt.motivation, rebuilt.source) == text


def test_unanswered_turn_roundtrip_keeps_moderator_note():
    turn = PanelTurn(
        turn_id="turn_gap",
        speaker="Spinndoktor",
        phase="unanswered",
        content="Panelen saknar rätt kompetens för frågan.",
        round_index=1,
        sub_question_id="finansiell_halsa",
    )
    note = unanswered_from_committed_turn(
        turn,
        sub_question=SubQuestionRef(id="finansiell_halsa", label="Finansiell hälsa"),
    )
    assert note.sub_question_id == "finansiell_halsa"
    assert note.moderator_note == turn.content


@pytest.mark.asyncio
async def test_resume_after_committed_score_skips_model_and_matches_transcript(client_db):
    _client, factory = client_db
    phase = {"resume": False}
    calls = {"score": 0, "score_resume_committed": 0, "tools_score": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        identity = "".join(
            item.get("content") or "" for item in messages if item.get("role") == "system"
        )
        if "Första raden: JA eller NEJ" in user or "First line: YES or NO" in user:
            return "JA\nDelfrågan är min kärnkompetens."
        if "ENDAST med JSON" in user or "ONLY with JSON" in user:
            committed = (
                "Finansiell hälsa" in user and "Finansiell analytiker" in identity
            )
            if phase["resume"] and committed:
                calls["score_resume_committed"] += 1
                raise AssertionError("resume rescored a committed turn")
            calls["score"] += 1
            if not phase["resume"] and calls["score"] > 1:
                raise RuntimeError("stop after first score")
            return json.dumps(
                {"score": 7, "motivation": "Committad bedömning av finansiell hälsa."}
            )
        if "Poängtabell" in user or "Score table" in user:
            return "Sammanfattning efter resume."
        if "Nuvarande delfråga" in user or "Current sub-question" in user:
            return "Vi går vidare till nästa delfråga."
        if "Öppna panelen" in user or "Open briefly" in user:
            return "Välkommen till DD-panelen."
        if "Ingen av experterna" in user or "None of the experts" in user:
            return "Panelen saknar rätt kompetens för frågan."
        return "OK"

    async def _tools(messages, tools=None):
        user = messages[-1]["content"]
        if "ENDAST med JSON" in user or "ONLY with JSON" in user:
            calls["tools_score"] += 1
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)

    async with factory() as db:
        customer_id = await default_os_customer_id(db)
        prompts = await require_active_prompts(
            db, customer_id=customer_id, module="dd", language="sv"
        )
        created = await create_panel_session(db, PanelSessionCreate(config=_config()))
        row = await get_panel_session(db, created.id)
        assert row is not None
        with pytest.raises(RuntimeError, match="stop after first score"):
            await run_structured_scoring(db, row, prompts)
        await db.commit()
        crashed = await get_panel_session(db, created.id)
        assert crashed is not None
        committed_scores = _score_turns(crashed.transcript)
        assert len(committed_scores) == 1
        committed_text = committed_scores[0]["content"]
        assert "Committad bedömning av finansiell hälsa." in committed_text

        phase["resume"] = True
        resume_score_before = calls["score"]
        resume_tools_before = calls["tools_score"]
        await run_structured_scoring(db, crashed, prompts)
        await db.commit()
        finished = await get_panel_session(db, created.id)

    assert finished is not None
    assert calls["score_resume_committed"] == 0
    assert calls["score"] > resume_score_before
    assert calls["tools_score"] >= resume_tools_before
    result = dd_panel_result_from_stored(finished.result or {})
    score_texts = [
        format_score_turn(row.score, row.motivation, row.source) for row in result.scores
    ]
    assert score_texts == [turn["content"] for turn in _score_turns(finished.transcript)]
    assert score_texts[0] == committed_text
    assert result.scores[0].motivation == "Committad bedömning av finansiell hälsa."


@pytest.mark.asyncio
async def test_resume_after_committed_unanswered_skips_model_and_keeps_note(client_db):
    _client, factory = client_db
    phase = {"resume": False}
    calls = {"unanswered": 0, "unanswered_resume_committed": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "Första raden: JA eller NEJ" in user or "First line: YES or NO" in user:
            return "NEJ\nJag avstår i sakfrågan."
        if "Ingen av experterna" in user or "None of the experts" in user:
            if phase["resume"] and "Finansiell hälsa" in user:
                calls["unanswered_resume_committed"] += 1
                raise AssertionError("resume regenerated a committed unanswered turn")
            calls["unanswered"] += 1
            return "Committad lucka för finansiell hälsa."
        if "Nuvarande delfråga" in user or "Current sub-question" in user:
            if not phase["resume"] and "Legal risk" in user:
                raise RuntimeError("stop after first unanswered")
            return "Vi går vidare till nästa delfråga."
        if "Poängtabell" in user or "Score table" in user:
            return "Sammanfattning med luckor."
        if "Öppna panelen" in user or "Open briefly" in user:
            return "Välkommen till DD-panelen."
        if "ENDAST med JSON" in user or "ONLY with JSON" in user:
            raise AssertionError("score called while every expert abstained")
        return "OK"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)

    async with factory() as db:
        customer_id = await default_os_customer_id(db)
        prompts = await require_active_prompts(
            db, customer_id=customer_id, module="dd", language="sv"
        )
        created = await create_panel_session(db, PanelSessionCreate(config=_config()))
        row = await get_panel_session(db, created.id)
        assert row is not None
        with pytest.raises(RuntimeError, match="stop after first unanswered"):
            await run_structured_scoring(db, row, prompts)
        await db.commit()
        crashed = await get_panel_session(db, created.id)
        assert crashed is not None
        committed_gaps = _unanswered_turns(crashed.transcript)
        assert len(committed_gaps) == 1
        committed_note = committed_gaps[0]["content"]
        assert committed_note == "Committad lucka för finansiell hälsa."

        phase["resume"] = True
        unanswered_before = calls["unanswered"]
        await run_structured_scoring(db, crashed, prompts)
        await db.commit()
        finished = await get_panel_session(db, created.id)

    assert finished is not None
    assert calls["unanswered_resume_committed"] == 0
    assert calls["unanswered"] > unanswered_before
    result = dd_panel_result_from_stored(finished.result or {})
    assert [note.moderator_note for note in result.unanswered] == [
        turn["content"] for turn in _unanswered_turns(finished.transcript)
    ]
    assert result.unanswered[0].moderator_note == committed_note
    assert result.scores == []
