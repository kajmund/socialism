"""Fas 4 — parallel relevance judge() and need-scoped Jev relevance."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import settings
from app.jev.system import JevSystemOneResult, JevUsage
from app.observability.research import research_obs_scope
from app.services.research.assessment import AssessableEvidence
from app.services.research.evidence_screen import (
    EVIDENCE_SCREEN_QUESTIONS,
    EvidenceJevScores,
    EvidenceScreenCache,
    JevEvidenceRelevanceAssessor,
    bind_attempt_relevance,
    relevance_from_jev_scores,
    screen_evidence,
)
from app.services.research.fast_gate import GatedResearchAssessor
from app.services.research.models import ResearchNeed
from app.services.research.quality import (
    FLAG_RELEVANCE_FAILED,
    EvidenceRelevanceJudgment,
    QualityEvidenceInput,
    assess_evidence_quality,
)


def _need(need_id: str = "need-1", question: str = "Vad gäller 36 §?") -> ResearchNeed:
    return ResearchNeed(
        id=need_id,
        question=question,
        why_needed="behövs",
        source_types=["swedish_law"],
    )


def _input(**overrides: object) -> QualityEvidenceInput:
    values: dict[str, object] = {
        "item_id": "item-1",
        "original_evidence_id": "ev-1",
        "research_need_id": "need-1",
        "source_type": "swedish_law",
        "status": "found",
        "title": "Titel",
        "excerpt": "Utdrag",
        "locator": None,
        "source_id": None,
        "source_url": None,
        "provider": "lagen.nu",
        "provenance": {},
        "retrieved_at": datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        "content_hash": "hash-1",
    }
    values.update(overrides)
    return QualityEvidenceInput(**values)  # type: ignore[arg-type]


def _assessable(**overrides: object) -> AssessableEvidence:
    values: dict[str, object] = {
        "evidence_id": "ev-1",
        "research_need_id": "need-1",
        "source_type": "swedish_law",
        "status": "found",
        "title": "Titel",
        "excerpt": "Utdrag",
        "locator": None,
        "source_id": None,
        "source_url": None,
        "provider": "lagen.nu",
        "score": None,
        "provenance": {},
        "retrieved_at": datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        "content_hash": "hash-1",
    }
    values.update(overrides)
    return AssessableEvidence(**values)  # type: ignore[arg-type]


def _noul(**values: float) -> dict[str, Any]:
    return {key: {"noul": value} for key, value in values.items()}


def _screen_nouls(
    *,
    relevant_to_question: float = 0.9,
    directly_supports_answer: float = 0.8,
) -> dict[str, Any]:
    return _noul(
        relevant_to_question=relevant_to_question,
        directly_supports_answer=directly_supports_answer,
        contradicts_current_evidence=0.1,
        material_new_information=0.7,
        likely_duplicate_or_redundant=0.1,
        primary_or_high_authority_for_question=0.6,
    )


def _result(answers: dict[str, Any], latency_ms: float = 3.0) -> JevSystemOneResult:
    return JevSystemOneResult(
        answers=answers,
        model="jev-latest",
        latency_ms=latency_ms,
        input_chars=240,
        usage=JevUsage(),
        raw={"answers": answers},
    )


class ScriptedScreenJev:
    def __init__(self, answers: dict[str, Any] | Exception) -> None:
        self.answers = answers
        self.states: list[object] = []

    async def ask(self, *, state, questions, model, timeout_seconds):
        del questions, model, timeout_seconds
        self.states.append(state)
        if isinstance(self.answers, Exception):
            raise self.answers
        return _result(self.answers)


class SleepingAssessor:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def judge(self, need: ResearchNeed, item: QualityEvidenceInput):
        del need
        self.seen.append(item.item_id)
        await asyncio.sleep(0.05)
        return EvidenceRelevanceJudgment(
            relevance="high",
            model_provider="test",
            model_name="sleep",
        )


class FixedAssessor:
    def __init__(self) -> None:
        self.calls = 0

    async def judge(self, need: ResearchNeed, item: QualityEvidenceInput):
        del need, item
        self.calls += 1
        return EvidenceRelevanceJudgment(
            relevance="medium",
            model_provider="cerebras",
            model_name="gpt-oss-120b",
            model_version="1",
        )


def _scores(
    *,
    relevant_to_question: float,
    directly_supports_answer: float,
) -> EvidenceJevScores:
    return EvidenceJevScores(
        evidence_id="ev-1",
        source_type="swedish_law",
        content_hash="hash-1",
        relevant_to_question=relevant_to_question,
        directly_supports_answer=directly_supports_answer,
        contradicts_current_evidence=0.1,
        material_new_information=0.7,
        likely_duplicate_or_redundant=0.1,
        primary_or_high_authority_for_question=0.6,
        latency_ms=3.0,
    )


@pytest.fixture
def jev_settings(monkeypatch):
    monkeypatch.setattr(settings, "research_jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-typesafe-key")
    monkeypatch.setattr(settings, "research_jev_evidence_screen_enabled", True)
    monkeypatch.setattr(settings, "research_jev_model", "jev-test")
    yield


def test_relevance_mapping_boundaries():
    assert relevance_from_jev_scores(_scores(relevant_to_question=0.8, directly_supports_answer=0.5)) == "high"
    assert relevance_from_jev_scores(_scores(relevant_to_question=0.8, directly_supports_answer=0.499)) == "medium"
    assert relevance_from_jev_scores(_scores(relevant_to_question=0.5, directly_supports_answer=0.0)) == "medium"
    assert relevance_from_jev_scores(_scores(relevant_to_question=0.499, directly_supports_answer=1.0)) == "low"


@pytest.mark.asyncio
async def test_parallel_judge_preserves_order_and_overlaps(monkeypatch):
    monkeypatch.setattr(settings, "research_relevance_concurrency", 8)
    items = [_input(item_id=f"item-{index}", content_hash=f"h{index}") for index in range(10)]
    assessor = SleepingAssessor()
    started = time.perf_counter()
    drafts = await assess_evidence_quality(items, needs=[_need()], relevance_assessor=assessor)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert [draft.evidence_set_item_id for draft in drafts] == [item.item_id for item in items]
    assert [draft.relevance for draft in drafts] == ["high"] * 10
    assert elapsed_ms < 200


@pytest.mark.asyncio
async def test_jev_failure_uses_inner_assessor(jev_settings):
    inner = FixedAssessor()
    assessor = JevEvidenceRelevanceAssessor(
        inner=inner,
        client=ScriptedScreenJev(TimeoutError("jev down")),
    )
    with research_obs_scope() as stats:
        judgment = await assessor.judge(_need(), _input())
    assert judgment.relevance == "medium"
    assert judgment.model_provider == "cerebras"
    assert inner.calls == 1
    assert stats.relevance_llm_fallbacks == 1
    assert judgment.failed is False


@pytest.mark.asyncio
async def test_jev_failure_without_inner_is_unknown_and_flagged(jev_settings):
    assessor = JevEvidenceRelevanceAssessor(
        client=ScriptedScreenJev(TimeoutError("jev down")),
    )
    drafts = await assess_evidence_quality(
        [_input()],
        needs=[_need()],
        relevance_assessor=assessor,
    )
    assert drafts[0].relevance == "unknown"
    assert FLAG_RELEVANCE_FAILED in {flag.code for flag in drafts[0].flags}


@pytest.mark.asyncio
async def test_same_item_two_need_questions_are_separate_cache_entries(jev_settings):
    client = ScriptedScreenJev(_screen_nouls())
    cache = EvidenceScreenCache()
    assessor = JevEvidenceRelevanceAssessor(cache=cache, client=client)
    item = _input()
    first = await assessor.judge(_need("need-1", "Fråga A"), item)
    second = await assessor.judge(_need("need-2", "Fråga B"), item)
    assert first.relevance == "high"
    assert second.relevance == "high"
    assert len(client.states) == 2
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_same_item_identical_need_questions_share_one_call(jev_settings):
    client = ScriptedScreenJev(_screen_nouls())
    cache = EvidenceScreenCache()
    assessor = JevEvidenceRelevanceAssessor(cache=cache, client=client)
    item = _input()
    await assessor.judge(_need("need-1", "Samma fråga"), item)
    await assessor.judge(_need("need-2", "Samma fråga"), item)
    assert len(client.states) == 1
    assert len(cache) == 1


@pytest.mark.asyncio
async def test_changed_question_set_misses_cache(jev_settings, monkeypatch):
    client = ScriptedScreenJev(_screen_nouls())
    cache = EvidenceScreenCache()
    assessor = JevEvidenceRelevanceAssessor(cache=cache, client=client)
    item = _input()
    await assessor.judge(_need(), item)
    changed = dict(EVIDENCE_SCREEN_QUESTIONS)
    changed["extra_probe"] = {
        "type": "noul",
        "instructions": "extra",
        "criteria": {"true": "yes", "false": "no"},
    }
    monkeypatch.setattr(
        "app.services.research.evidence_screen.EVIDENCE_SCREEN_QUESTIONS",
        changed,
    )
    await assessor.judge(_need(), item)
    assert len(client.states) == 2
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_screening_and_need_relevance_do_not_share_cache(jev_settings):
    client = ScriptedScreenJev(_screen_nouls())
    cache = EvidenceScreenCache()
    item = _assessable()
    await screen_evidence(
        objective="Fråga A Fråga B",
        evidence=[item],
        client=client,
        cache=cache,
    )
    assessor = JevEvidenceRelevanceAssessor(cache=cache, client=client)
    await assessor.judge(_need("need-1", "Fråga A"), _input())
    assert len(client.states) == 2
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_llm_source_quality_rows_are_bit_identical(monkeypatch):
    monkeypatch.setattr(settings, "research_relevance_source", "llm")
    assessor = FixedAssessor()
    items = [_input(item_id="a"), _input(item_id="b", content_hash="hash-2")]
    first = await assess_evidence_quality(items, needs=[_need()], relevance_assessor=assessor)
    second = await assess_evidence_quality(items, needs=[_need()], relevance_assessor=assessor)
    assert [_row_identity(draft) for draft in first] == [_row_identity(draft) for draft in second]


def test_production_default_keeps_injected_assessor(monkeypatch):
    monkeypatch.setattr(settings, "research_relevance_source", "llm")
    injected = FixedAssessor()
    _cache, bound = bind_attempt_relevance(GatedResearchAssessor(FixedAssessor()), injected)
    assert bound is injected


def test_jev_source_wraps_injected_assessor(monkeypatch):
    monkeypatch.setattr(settings, "research_relevance_source", "jev")
    injected = FixedAssessor()
    _cache, bound = bind_attempt_relevance(object(), injected)
    assert isinstance(bound, JevEvidenceRelevanceAssessor)


def _row_identity(draft: object) -> tuple[object, ...]:
    return (
        draft.evidence_set_item_id,
        draft.original_evidence_id,
        draft.scoring_policy_version,
        draft.authority,
        draft.relevance,
        draft.currentness,
        draft.source_nature,
        draft.source_timestamp,
        draft.independence_key,
        draft.independent_source_count,
        tuple((flag.code, flag.detail) for flag in draft.flags),
        draft.rationale,
        draft.model_provider,
        draft.model_name,
        draft.model_version,
    )
