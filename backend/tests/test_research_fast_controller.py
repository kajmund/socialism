"""Jev research fast controller: gating, fallback, ELK fields, no evidence mutation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import settings
from app.llm.jev_system import (
    JevClientError,
    JevSystemOneResult,
    JevUsage,
    parse_noul,
)
from app.observability.events import EVENT_PAYLOAD_ATTR
from app.observability.research import (
    EVENT_JEV_ASSESSMENT_COMPLETED,
    EVENT_JEV_ASSESSMENT_FAILED,
    EVENT_JEV_SHADOW_COMPARISON,
    EVENT_JEV_SHORT_CIRCUIT,
    EVENT_RESEARCH_EXECUTION_SUMMARY,
    research_obs_scope,
)
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.completeness import ResearchCompletenessDraft
from app.services.research.evidence_screen import order_evidence_for_state, screen_evidence
from app.services.research.fast_controller import (
    ResearchFastController,
    classify_research_decision,
    research_jev_available,
)
from app.services.research.fast_gate import (
    GatedResearchAssessor,
    GatedResearchCompletenessReviewer,
)
from app.services.research.fast_state import compact_research_state
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import ResearchObjective


@pytest.fixture
def jev_settings(monkeypatch):
    monkeypatch.setattr(settings, "research_jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-typesafe-key")
    monkeypatch.setattr(settings, "research_jev_mode", "shadow")
    monkeypatch.setattr(settings, "research_jev_sufficient_threshold", 0.9)
    monkeypatch.setattr(settings, "research_jev_incomplete_threshold", 0.85)
    monkeypatch.setattr(settings, "research_jev_confidence_threshold", 0.8)
    monkeypatch.setattr(settings, "research_jev_evidence_screen_enabled", False)
    monkeypatch.setattr(settings, "research_jev_max_evidence_items", 8)
    monkeypatch.setattr(settings, "research_jev_max_state_chars", 4000)
    monkeypatch.setattr(settings, "research_jev_concurrency", 4)
    yield


def _noul(**values: float) -> dict[str, Any]:
    return {key: {"noul": value} for key, value in values.items()}


def _sufficient_nouls() -> dict[str, Any]:
    return _noul(
        answerable_now=0.96,
        material_gap=0.03,
        contradiction=0.02,
        follow_up_change=0.04,
        additional_source=0.03,
    )


def _uncertain_nouls() -> dict[str, Any]:
    return _noul(
        answerable_now=0.61,
        material_gap=0.44,
        contradiction=0.33,
        follow_up_change=0.48,
        additional_source=0.40,
    )


def _insufficient_nouls() -> dict[str, Any]:
    return _noul(
        answerable_now=0.08,
        material_gap=0.94,
        contradiction=0.12,
        follow_up_change=0.88,
        additional_source=0.71,
    )


def _result(answers: dict[str, Any], *, latency_ms: float = 12.0) -> JevSystemOneResult:
    return JevSystemOneResult(
        answers=answers,
        model="jev-1.12",
        latency_ms=latency_ms,
        input_chars=240,
        usage=JevUsage(prompt_tokens=11, completion_tokens=4, total_tokens=15),
        raw={"answers": answers},
    )


class ScriptedJev:
    def __init__(
        self,
        assessment: dict[str, Any] | Exception,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.assessment = assessment
        self.evidence = evidence or _noul(
            relevant_to_question=0.9,
            directly_supports_answer=0.8,
            contradicts_current_evidence=0.1,
            material_new_information=0.7,
            likely_duplicate_or_redundant=0.1,
            primary_or_high_authority_for_question=0.6,
        )
        self.states: list[object] = []
        self.question_sets: list[tuple[str, ...]] = []

    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult:
        del model, timeout_seconds
        self.states.append(state)
        keys = tuple(sorted(questions))
        self.question_sets.append(keys)
        if "relevant_to_question" in questions:
            return _result(self.evidence, latency_ms=3.0)
        if isinstance(self.assessment, Exception):
            raise self.assessment
        return _result(self.assessment)


class RecordingAssessor:
    def __init__(self, draft: ResearchAssessmentDraft) -> None:
        self.calls = 0
        self.evidence_ids: list[tuple[str, ...]] = []
        self.draft = draft

    async def assess(self, plan, evidence) -> ResearchAssessmentDraft:
        del plan
        self.calls += 1
        self.evidence_ids.append(tuple(item.evidence_id for item in evidence))
        return self.draft


class RecordingCompleteness:
    def __init__(self, draft: ResearchCompletenessDraft) -> None:
        self.calls = 0
        self.draft = draft

    async def review(self, **_kwargs) -> ResearchCompletenessDraft:
        self.calls += 1
        return self.draft


def _plan() -> ResearchPlan:
    return ResearchPlan(
        needs=[
            ResearchNeed(
                id="need-1",
                question="Vad gäller skattesatsen?",
                why_needed="beslut",
                source_types=["swedish_law"],
            )
        ]
    )


def _evidence(*, excerpt: str = "lagtext om skatt") -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id="ev-1",
        research_need_id="need-1",
        source_type="swedish_law",
        status="found",
        title="SFS",
        excerpt=excerpt,
        locator="p1",
        source_id="sfs-1",
        source_url="https://example.test/sfs",
        provider="lagen_nu",
        score=0.8,
        provenance={"document_id": "sfs-1"},
        retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
        content_hash="hash-1",
    )


def _llm_draft(*, result: str = "insufficient") -> ResearchAssessmentDraft:
    return ResearchAssessmentDraft(
        result=result,  # type: ignore[arg-type]
        rationale="llm",
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id="need-1",
                sufficient=result == "sufficient",
                supporting_evidence_ids=["ev-1"] if result == "sufficient" else [],
                missing_or_weak="" if result == "sufficient" else "saknas",
                further_information=None if result == "sufficient" else "mer",
            )
        ],
        considered_evidence_ids=["ev-1"],
        model_provider="cerebras",
        model_name="gpt-oss-120b",
    )


def test_disabled_without_key(monkeypatch):
    monkeypatch.setattr(settings, "research_jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    assert research_jev_available() is False


def test_classify_sufficient_and_uncertain():
    assert (
        classify_research_decision(
            answerable_now=0.96,
            material_gap=0.03,
            contradiction=0.02,
            follow_up_change=0.04,
            additional_source=0.03,
            confidence=0.96,
            sufficient_threshold=0.9,
            incomplete_threshold=0.85,
            confidence_threshold=0.8,
        )
        == "sufficient"
    )
    assert (
        classify_research_decision(
            answerable_now=0.55,
            material_gap=0.48,
            contradiction=0.4,
            follow_up_change=0.5,
            additional_source=0.45,
            confidence=0.55,
            sufficient_threshold=0.9,
            incomplete_threshold=0.85,
            confidence_threshold=0.8,
        )
        == "uncertain"
    )
    assert (
        classify_research_decision(
            answerable_now=0.08,
            material_gap=0.93,
            contradiction=0.1,
            follow_up_change=0.9,
            additional_source=0.2,
            confidence=0.93,
            sufficient_threshold=0.9,
            incomplete_threshold=0.85,
            confidence_threshold=0.8,
        )
        == "insufficient"
    )


def test_compact_state_is_deterministic_and_clipped():
    plan = _plan()
    huge = _evidence(excerpt="x" * 5000)
    first = compact_research_state(
        objective="skatt",
        plan=plan,
        evidence=[huge],
        max_evidence_items=1,
        max_state_chars=800,
    )
    second = compact_research_state(
        objective="skatt",
        plan=plan,
        evidence=[huge],
        max_evidence_items=1,
        max_state_chars=800,
    )
    assert first.payload == second.payload
    assert first.input_sha256 == second.input_sha256
    excerpt = first.payload["evidence"][0]["excerpt"]
    assert excerpt is not None
    assert len(excerpt) <= 280
    assert "x" * 400 not in excerpt


@pytest.mark.asyncio
async def test_disabled_gate_is_identical_to_inner(monkeypatch):
    monkeypatch.setattr(settings, "research_jev_enabled", False)
    inner = RecordingAssessor(_llm_draft())
    client = ScriptedJev(_sufficient_nouls())
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    draft = await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 1
    assert client.states == []
    assert draft.rationale == "llm"


@pytest.mark.asyncio
async def test_jev_error_falls_back_to_llm(jev_settings, caplog):
    inner = RecordingAssessor(_llm_draft())
    client = ScriptedJev(
        JevClientError("timed out", category="timeout")
    )
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    with caplog.at_level("INFO"):
        draft = await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 1
    assert draft.rationale == "llm"
    assert EVENT_JEV_ASSESSMENT_FAILED in caplog.text


@pytest.mark.asyncio
async def test_high_confidence_sufficient_skips_assessor(jev_settings):
    settings.research_jev_mode = "active"
    inner = RecordingAssessor(_llm_draft())
    client = ScriptedJev(_sufficient_nouls())
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    with research_obs_scope() as stats:
        draft = await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 0
    assert draft.result == "sufficient"
    assert draft.need_assessments[0].supporting_evidence_ids == ["ev-1"]
    assert draft.model_provider == "jev"
    assert stats.assessor_llm_skipped == 1
    assert stats.assessor_llm_calls == 0


@pytest.mark.asyncio
async def test_uncertain_calls_current_llm(jev_settings):
    settings.research_jev_mode = "active"
    inner = RecordingAssessor(_llm_draft())
    client = ScriptedJev(_uncertain_nouls())
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    draft = await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 1
    assert draft.rationale == "llm"


@pytest.mark.asyncio
async def test_high_confidence_insufficient_does_not_complete(jev_settings):
    settings.research_jev_mode = "active"
    inner = RecordingAssessor(_llm_draft(result="insufficient"))
    client = ScriptedJev(_insufficient_nouls())
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    draft = await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 1
    assert draft.result == "insufficient"


@pytest.mark.asyncio
async def test_shadow_mode_never_skips_llm(jev_settings, caplog):
    settings.research_jev_mode = "shadow"
    inner = RecordingAssessor(_llm_draft(result="insufficient"))
    client = ScriptedJev(_sufficient_nouls())
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    with caplog.at_level("INFO"):
        draft = await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 1
    assert draft.result == "insufficient"
    assert EVENT_JEV_SHADOW_COMPARISON in caplog.text
    assert EVENT_JEV_SHORT_CIRCUIT not in caplog.text
    payload = None
    for record in caplog.records:
        extra = getattr(record, EVENT_PAYLOAD_ATTR, None)
        if extra and extra.get("event", {}).get("name") == EVENT_JEV_SHADOW_COMPARISON:
            payload = extra
    assert payload is not None
    assert payload["research"]["false_sufficient_candidate"] is True
    assert payload["research"]["would_have_short_circuited"] is True
    assert payload["jev"]["decision"] == "sufficient"
    assert payload["research"]["llm_decision"] == "insufficient"


@pytest.mark.asyncio
async def test_completeness_active_skip(jev_settings):
    settings.research_jev_mode = "active"
    inner = RecordingCompleteness(
        ResearchCompletenessDraft(result="incomplete", rationale="llm")
    )
    client = ScriptedJev(_sufficient_nouls())
    gated = GatedResearchCompletenessReviewer(inner, ResearchFastController(client))
    with research_obs_scope() as stats:
        draft = await gated.review(
            objective=ResearchObjective(objective="Vad gäller skattesatsen?"),
            plan=_plan(),
            runtime_needs=[
                RuntimeResearchNeed(
                    research_need_id="need-1",
                    question="Vad gäller skattesatsen?",
                    why_needed="beslut",
                    source_types=["swedish_law"],
                )
            ],
            assessment=None,
            assessments=[],
            evidence=[_evidence()],
        )
    assert inner.calls == 0
    assert draft.result == "complete"
    assert stats.completeness_llm_skipped == 1
    assert stats.follow_up_waves_avoided == 1


def test_probability_validation():
    with pytest.raises(JevClientError) as missing:
        parse_noul({}, "answerable_now")
    assert missing.value.category == "schema_validation"
    with pytest.raises(JevClientError) as ranged:
        parse_noul({"answerable_now": {"noul": 1.2}}, "answerable_now")
    assert ranged.value.category == "schema_validation"
    with pytest.raises(JevClientError) as typed:
        parse_noul({"answerable_now": {"noul": "nope"}}, "answerable_now")
    assert typed.value.category == "schema_validation"


@pytest.mark.asyncio
async def test_invalid_noul_falls_back(jev_settings):
    inner = RecordingAssessor(_llm_draft())
    client = ScriptedJev({"answerable_now": {"noul": "nope"}})
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    draft = await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 1
    assert draft.rationale == "llm"


@pytest.mark.asyncio
async def test_evidence_screen_does_not_mutate_or_drop(jev_settings):
    settings.research_jev_evidence_screen_enabled = True
    first = _evidence()
    second = AssessableEvidence(
        evidence_id="ev-2",
        research_need_id="need-1",
        source_type="web",
        status="found",
        title="blogg",
        excerpt="samma sak",
        locator="p2",
        source_id="blog",
        source_url="https://example.test/blog",
        provider="web",
        score=0.2,
        provenance={"document_id": "blog"},
        retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
        content_hash="hash-2",
    )
    original_excerpt = first.excerpt
    client = ScriptedJev(_sufficient_nouls())
    scores = await screen_evidence(
        objective="skatt",
        evidence=[first, second],
        client=client,
    )
    assert {row.evidence_id for row in scores} == {"ev-1", "ev-2"}
    assert first.excerpt == original_excerpt
    assert first.provenance == {"document_id": "sfs-1"}
    ordered = order_evidence_for_state([first, second], scores)
    assert {item.evidence_id for item in ordered} == {"ev-1", "ev-2"}


@pytest.mark.asyncio
async def test_evidence_screen_concurrency_isolation(jev_settings):
    settings.research_jev_evidence_screen_enabled = True
    settings.research_jev_concurrency = 2

    class SlowJev:
        def __init__(self) -> None:
            self.in_flight = 0
            self.max_in_flight = 0
            self.seen: list[str] = []

        async def ask(self, *, state, questions, model, timeout_seconds):
            del questions, model, timeout_seconds
            evidence = state["evidence"]
            self.seen.append(evidence["evidence_id"])
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            await asyncio.sleep(0.01)
            self.in_flight -= 1
            return _result(
                _noul(
                    relevant_to_question=0.5,
                    directly_supports_answer=0.5,
                    contradicts_current_evidence=0.1,
                    material_new_information=0.5,
                    likely_duplicate_or_redundant=0.1,
                    primary_or_high_authority_for_question=0.5,
                )
            )

    items = [
        AssessableEvidence(
            evidence_id=f"ev-{index}",
            research_need_id="need-1",
            source_type="swedish_law",
            status="found",
            title=f"T{index}",
            excerpt=f"text-{index}",
            locator=f"p{index}",
            source_id=f"s{index}",
            source_url=None,
            provider="fake",
            score=None,
            provenance={},
            retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
            content_hash=f"h{index}",
        )
        for index in range(4)
    ]
    client = SlowJev()
    scores = await screen_evidence(objective="q", evidence=items, client=client)
    assert len(scores) == 4
    assert client.max_in_flight <= 2
    assert sorted(client.seen) == ["ev-0", "ev-1", "ev-2", "ev-3"]


@pytest.mark.asyncio
async def test_representative_shadow_comparison_measures_skip_opportunity(
    jev_settings, caplog
):
    """Replay-style: Jev would skip the assessor; LLM still ran in shadow."""
    settings.research_jev_mode = "shadow"
    inner = RecordingAssessor(_llm_draft(result="sufficient"))
    client = ScriptedJev(_sufficient_nouls())
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    with research_obs_scope() as stats:
        with caplog.at_level("INFO"):
            await gated.assess(_plan(), [_evidence()])
    assert inner.calls == 1
    assert stats.assessor_llm_skipped == 0
    comparison = None
    completed = None
    for record in caplog.records:
        extra = getattr(record, EVENT_PAYLOAD_ATTR, None)
        if not extra:
            continue
        name = extra.get("event", {}).get("name")
        if name == EVENT_JEV_SHADOW_COMPARISON:
            comparison = extra
        if name == EVENT_JEV_ASSESSMENT_COMPLETED:
            completed = extra
    assert completed is not None
    assert completed["jev"]["answerable_now_probability"] == 0.96
    assert completed["jev"]["decision"] == "sufficient"
    assert completed["jev"]["mode"] == "shadow"
    assert comparison is not None
    assert comparison["research"]["agreement"] is True
    assert comparison["research"]["estimated_avoided_llm_calls"] == 1
    assert comparison["research"]["false_sufficient_candidate"] is False
    assert comparison["jev"]["latency_ms"] == 12.0
    assert comparison["research"]["llm_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_structured_assessment_event_has_kibana_fields(jev_settings, caplog):
    inner = RecordingAssessor(_llm_draft())
    client = ScriptedJev(_uncertain_nouls())
    gated = GatedResearchAssessor(inner, ResearchFastController(client))
    with caplog.at_level("INFO"):
        await gated.assess(_plan(), [_evidence()])
    completed = None
    for record in caplog.records:
        extra = getattr(record, EVENT_PAYLOAD_ATTR, None)
        if extra and extra.get("event", {}).get("name") == EVENT_JEV_ASSESSMENT_COMPLETED:
            completed = extra
    assert completed is not None
    jev = completed["jev"]
    for key in (
        "provider",
        "model",
        "mode",
        "decision",
        "answerable_now_probability",
        "material_gap_probability",
        "contradiction_probability",
        "follow_up_change_probability",
        "additional_source_probability",
        "decision_confidence",
        "sufficient_threshold",
        "incomplete_threshold",
        "confidence_threshold",
        "latency_ms",
        "input_chars",
        "fallback_used",
        "fallback_reason",
    ):
        assert key in jev
    assert jev["provider"] == "jev"
    assert "excerpt" not in str(completed)
    assert "lagtext" not in str(completed)


def test_summary_event_name_is_stable():
    assert EVENT_RESEARCH_EXECUTION_SUMMARY == "research.execution.summary"
