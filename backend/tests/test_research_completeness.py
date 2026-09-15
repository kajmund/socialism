"""Global completeness gate: local sufficient is not the freeze barrier."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.llm.research_completeness import CompletenessModel, LlmResearchCompletenessReviewer
from app.services.execution import (
    get_attempt,
    get_evidence_set,
    list_need_executions,
    list_research_completeness_passes,
    list_runtime_needs,
)
from app.services.research.completeness import (
    MaterialMissingQuestion,
    ResearchCompletenessDraft,
    ResearchCompletenessError,
    question_fingerprint,
    sanitize_completeness_draft,
)
from app.services.research.execution import ResearchExecutionError, execute_attempt_research
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchPlan
from app.services.research.planner import ResearchObjective
from app.services.research.provider import knowledge_adapter_descriptor
from app.services.research.registry import (
    default_standard_capability_descriptors,
    set_standard_capability_descriptors,
)
from tests.test_research_assessment import RecordingAssessor, _fixed_draft
from tests.test_research_execution import (
    RecordingSource,
    _created_attempt,
    _need,
    _router,
)


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


class SequenceCompletenessReviewer:
    def __init__(self, drafts: list[ResearchCompletenessDraft]) -> None:
        self.drafts = drafts
        self.calls = 0
        self.available_source_types_calls: list[tuple[str, ...]] = []

    async def review(self, **kwargs) -> ResearchCompletenessDraft:
        offered = kwargs.get("available_source_types")
        self.available_source_types_calls.append(tuple(offered or ()))
        draft = self.drafts[min(self.calls, len(self.drafts) - 1)]
        self.calls += 1
        return draft


class BoomCompletenessReviewer:
    async def review(self, **_kwargs):
        raise RuntimeError("completeness exploded")


def _objective(text: str = "Kartlägg skatterisk och transaktionshistorik") -> ResearchObjective:
    return ResearchObjective(objective=text, context={"topic": "skatt"})


def _missing(
    question: str,
    *,
    why: str = "Målet kräver transaktionshistorik",
    source_types: list[str] | None = None,
) -> MaterialMissingQuestion:
    return MaterialMissingQuestion(
        question=question,
        why_needed=why,
        rationale=why,
        source_types=source_types or ["case_knowledge"],  # type: ignore[arg-type]
    )


def _incomplete(*questions: MaterialMissingQuestion) -> ResearchCompletenessDraft:
    return ResearchCompletenessDraft(
        result="incomplete",
        rationale="Lokalt tillräckligt men målet saknar en materiell fråga.",
        missing_questions=list(questions),
        model_provider="scripted",
        model_name="completeness-test",
    )


def _complete(rationale: str = "Målet är täckt.") -> ResearchCompletenessDraft:
    return ResearchCompletenessDraft(
        result="complete",
        rationale=rationale,
        model_provider="scripted",
        model_name="completeness-test",
    )


@pytest.mark.asyncio
async def test_local_sufficient_but_objective_gap_seeds_global_need(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-gap")
    retrieved: list[str] = []

    class TrackSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            retrieved.append(need.id)
            return await RecordingSource("case_knowledge").research(need, context)

    reviewer = SequenceCompletenessReviewer(
        [
            _incomplete(_missing("Vilka transaktioner skedde 2024?")),
            _complete(),
        ]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(TrackSource())[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        session_factory=factory,
    )
    reloaded = await get_attempt(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    passes = await list_research_completeness_passes(session, attempt.id)
    executions = await list_need_executions(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    global_needs = [row for row in needs if row.origin == "global_completeness"]
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "sufficient"
    assert evidence_set.status == "frozen"
    assert reviewer.calls == 2
    assert [row.result for row in passes] == ["incomplete", "complete"]
    assert len(global_needs) == 1
    assert global_needs[0].source_completeness_pass == 1
    assert global_needs[0].source_gap == "Målet kräver transaktionshistorik"
    assert global_needs[0].research_need_id.startswith("global_1_")
    assert global_needs[0].research_need_id in retrieved
    assert {row.status for row in executions} == {"completed"}
    assert reloaded.research_plan_snapshot["needs"][0]["id"] == "research_1"


@pytest.mark.asyncio
async def test_global_need_uses_existing_async_retrieval_path(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-async")
    attempt_id = attempt.id
    second_started = asyncio.Event()
    release_second = asyncio.Event()

    class GateSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            if need.id != "research_1":
                second_started.set()
                await release_second.wait()
            return await RecordingSource("case_knowledge").research(need, context)

    reviewer = SequenceCompletenessReviewer(
        [
            _incomplete(
                _missing("Fråga A om motparter"),
                _missing("Fråga B om belopp"),
            ),
            _complete(),
        ]
    )
    task = asyncio.create_task(
        execute_attempt_research(
            session,
            attempt_id=attempt_id,
            research_objective=_objective(),
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=_router(GateSource())[0],
            assessor=RecordingAssessor(),
            completeness_reviewer=reviewer,
            session_factory=factory,
        )
    )
    await asyncio.wait_for(second_started.wait(), timeout=2)
    async with factory() as mid:
        needs = await list_runtime_needs(mid, attempt_id)
        executions = await list_need_executions(mid, attempt_id)
        running = [row for row in executions if row.status == "running"]
        assert any(row.origin == "global_completeness" for row in needs)
        assert running
    release_second.set()
    result = await task
    assert result.status == "ready"


@pytest.mark.asyncio
async def test_duplicate_global_question_is_rejected(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-dup")
    reviewer = SequenceCompletenessReviewer(
        [_incomplete(_missing("Vad gäller skattesatsen?"))]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        max_completeness_passes=2,
    )
    reloaded = await get_attempt(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    passes = await list_research_completeness_passes(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "no_novel_followups"
    assert [row.origin for row in needs] == ["initial"]
    assert passes[0].result == "incomplete"
    assert reloaded.status == "ready"


@pytest.mark.asyncio
async def test_budget_stop_records_incomplete_state(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-budget")
    reviewer = SequenceCompletenessReviewer(
        [_incomplete(_missing("Ny materiell fråga"))]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        max_needs=1,
    )
    reloaded = await get_attempt(session, attempt.id)
    passes = await list_research_completeness_passes(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "max_needs"
    assert passes[0].result == "incomplete"
    assert [row.origin for row in needs] == ["initial"]
    assert evidence_set.status == "frozen"


@pytest.mark.asyncio
async def test_max_completeness_passes_stops_cycle(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-cycle")
    reviewer = SequenceCompletenessReviewer(
        [
            _incomplete(_missing("Första luckan")),
            _incomplete(_missing("Andra luckan efter evidens")),
        ]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        max_completeness_passes=2,
        max_follow_up_waves=4,
        max_needs=8,
    )
    reloaded = await get_attempt(session, attempt.id)
    passes = await list_research_completeness_passes(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "max_completeness_passes"
    assert [row.result for row in passes] == ["incomplete", "incomplete"]
    assert reviewer.calls == 2


@pytest.mark.asyncio
async def test_reviewer_failure_prevents_false_freeze(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-fail")
    with pytest.raises(ResearchExecutionError):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=_router(RecordingSource("case_knowledge"))[0],
            assessor=RecordingAssessor(),
            completeness_reviewer=BoomCompletenessReviewer(),
        )
    reloaded = await get_attempt(session, attempt.id)
    passes = await list_research_completeness_passes(session, attempt.id)
    assert reloaded.status == "failed"
    assert reloaded.evidence_set_id is not None
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    assert evidence_set.status == "failed"
    assert passes == []


@pytest.mark.asyncio
async def test_completeness_retry_is_idempotent(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-retry")
    reviewer = SequenceCompletenessReviewer([_complete()])
    first = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        session_factory=factory,
    )
    second = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        session_factory=factory,
    )
    passes = await list_research_completeness_passes(session, attempt.id)
    assert first.status == "ready"
    assert second.status == "ready"
    assert first.evidence_set_id == second.evidence_set_id
    assert [row.completeness_pass for row in passes] == [1]
    assert reviewer.calls == 1


@pytest.mark.asyncio
async def test_read_model_exposes_global_decision_and_lineage(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-read")
    reviewer = SequenceCompletenessReviewer(
        [
            _incomplete(_missing("Vilken motpart betalade?")),
            _complete(),
        ]
    )
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
    )
    passes = await list_research_completeness_passes(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    latest = passes[-1]
    assert latest.result == "complete"
    assert latest.evidence_fingerprint
    assert latest.question_fingerprint
    assert latest.model_provider == "scripted"
    global_need = next(row for row in needs if row.origin == "global_completeness")
    assert global_need.source_completeness_pass == 1
    assert global_need.source_assessment_pass is None


@pytest.mark.asyncio
async def test_no_objective_is_programmatic_complete(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-noobj")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
    )
    reloaded = await get_attempt(session, attempt.id)
    passes = await list_research_completeness_passes(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "sufficient"
    assert [row.result for row in passes] == ["complete"]
    assert "No persisted research objective" in passes[0].rationale


@pytest.mark.asyncio
async def test_llm_completeness_reviewer_validates_payload():
    captured = []

    async def completer(messages, response_model):
        captured.append(response_model)
        return CompletenessModel(
            result="incomplete",
            rationale="saknas motpart",
            missing_questions=[
                {
                    "question": "Vilken motpart?",
                    "why_needed": "målet kräver det",
                    "rationale": "aldrig ställd",
                    "source_types": ["case_knowledge"],
                }
            ],
        )

    reviewer = LlmResearchCompletenessReviewer(
        completer=completer,
        system_prompt="bedöm fullständighet",
        user_prompt=(
            "{source_types} {objective} {objective_json} {plan_json} "
            "{runtime_needs_json} {assessment_json} {assessments_json} {evidence_json}"
        ),
        provider="test",
        model="unit",
    )
    draft = await reviewer.review(
        objective=_objective(),
        plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        runtime_needs=[
            RuntimeResearchNeed(
                research_need_id="research_1",
                question="Vad gäller skattesatsen?",
                why_needed="behövs",
                source_types=["case_knowledge"],
            )
        ],
        assessment=_fixed_draft(
            result="sufficient", need_id="research_1", evidence_ids=[]
        ),
        assessments=[],
        evidence=[],
    )
    assert captured == [CompletenessModel]
    assert draft.result == "incomplete"
    assert draft.missing_questions[0].question == "Vilken motpart?"


@pytest.mark.asyncio
async def test_llm_completeness_failure_is_explicit():
    async def completer(messages, response_model):
        raise RuntimeError("model down")

    reviewer = LlmResearchCompletenessReviewer(
        completer=completer,
        system_prompt="bedöm fullständighet",
        user_prompt="{objective} {plan_json} {evidence_json}",
    )
    with pytest.raises(ResearchCompletenessError):
        await reviewer.review(
            objective=_objective(),
            plan=ResearchPlan(),
            runtime_needs=[],
            assessment=None,
            assessments=[],
            evidence=[],
        )


def test_sanitize_drops_duplicate_and_complete_candidates():
    needs = [
        RuntimeResearchNeed(
            research_need_id="research_1",
            question="Vad gäller skattesatsen?",
            why_needed="behövs",
            source_types=["case_knowledge"],
        )
    ]
    cleaned = sanitize_completeness_draft(
        ResearchCompletenessDraft(
            result="complete",
            rationale="ok",
            missing_questions=[_missing("Ny fråga")],
        ),
        runtime_needs=needs,
        evidence=[],
    )
    assert cleaned.missing_questions == []
    dropped = sanitize_completeness_draft(
        _incomplete(_missing("Vad gäller skattesatsen?"), _missing("Ny fråga")),
        runtime_needs=needs,
        evidence=[],
    )
    assert [row.question for row in dropped.missing_questions] == ["Ny fråga"]


def test_sanitize_keeps_identified_question_with_unavailable_source_type():
    cleaned = sanitize_completeness_draft(
        _incomplete(_missing("Vad säger skattelagen?", source_types=["swedish_law"])),
        runtime_needs=[],
        evidence=[],
        allowed_source_types=("case_knowledge",),
    )
    assert cleaned.result == "incomplete"
    question = cleaned.missing_questions[0]
    assert question.question == "Vad säger skattelagen?"
    assert question.source_types == []
    assert question.unavailable_source_types == ["swedish_law"]
    assert question.capability_gap == "unavailable source_type: swedish_law"


def test_sanitize_keeps_executable_types_on_mixed_question():
    cleaned = sanitize_completeness_draft(
        _incomplete(
            _missing(
                "Både ärende och lag?",
                source_types=["case_knowledge", "swedish_law"],
            )
        ),
        runtime_needs=[],
        evidence=[],
        allowed_source_types=("case_knowledge", "customer_knowledge"),
    )
    question = cleaned.missing_questions[0]
    assert question.source_types == ["case_knowledge"]
    assert question.unavailable_source_types == ["swedish_law"]
    assert question.capability_gap is None


@pytest.mark.asyncio
async def test_llm_completeness_reviewer_is_offered_only_executable_source_types():
    captured: list[list[dict]] = []

    async def completer(messages, response_model):
        captured.append(messages)
        return CompletenessModel(
            result="complete",
            rationale="ok",
            missing_questions=[],
        )

    reviewer = LlmResearchCompletenessReviewer(
        completer=completer,
        system_prompt="bedöm fullständighet",
        user_prompt="Tillåtna: {source_types}",
        source_types=("case_knowledge", "customer_knowledge", "swedish_law"),
    )
    draft = await reviewer.review(
        objective=_objective(),
        plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        runtime_needs=[],
        assessment=None,
        assessments=[],
        evidence=[],
        available_source_types=("case_knowledge",),
    )
    offered = captured[0][1]["content"]
    assert offered == "Tillåtna: case_knowledge"
    assert "swedish_law" not in offered
    assert "swedish_preparatory_works" not in offered
    assert "web" not in offered
    assert "domain_knowledge" not in offered
    assert draft.result == "complete"


@pytest.mark.asyncio
async def test_factory_path_offers_standard_capability_natures_to_completeness_reviewer(
    db,
):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-factory-cap")
    reviewer = SequenceCompletenessReviewer([_complete()])
    router, sources = _router(RecordingSource("case_knowledge"))
    bound_sessions: list[object] = []

    def router_factory(bound):
        bound_sessions.append(bound)
        return router

    set_standard_capability_descriptors(
        (
            *default_standard_capability_descriptors(),
            knowledge_adapter_descriptor("synthetic-provider", "swedish_law"),
        )
    )
    try:
        result = await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=None,
            router_factory=router_factory,
            assessor=RecordingAssessor(),
            completeness_reviewer=reviewer,
            session_factory=factory,
        )
    finally:
        set_standard_capability_descriptors(None)

    assert result.status == "ready"
    assert reviewer.available_source_types_calls
    offered = reviewer.available_source_types_calls[0]
    assert "swedish_law" in offered
    assert "case_knowledge" in offered
    assert "customer_knowledge" in offered
    assert bound_sessions
    assert session not in bound_sessions
    assert sources[0].calls == 1


@pytest.mark.asyncio
async def test_catalog_type_missing_from_capability_cannot_become_global_need(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="comp-factory-gap")
    reviewer = SequenceCompletenessReviewer(
        [_incomplete(_missing("Vad säger webben?", source_types=["web"]))]
    )
    router, sources = _router(RecordingSource("case_knowledge"))
    bound_sessions: list[object] = []

    def router_factory(bound):
        bound_sessions.append(bound)
        return router

    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=None,
        router_factory=router_factory,
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        session_factory=factory,
    )
    reloaded = await get_attempt(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    passes = await list_research_completeness_passes(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "capability_unavailable"
    assert [row.origin for row in needs] == ["initial"]
    assert passes[0].result == "incomplete"
    missing = passes[0].missing_questions[0]
    assert missing["question"] == "Vad säger webben?"
    assert missing["source_types"] == []
    assert missing["unavailable_source_types"] == ["web"]
    assert missing["capability_gap"] == "unavailable source_type: web"
    assert bound_sessions
    assert session not in bound_sessions
    assert sources[0].calls == 1
    assert "web" not in reviewer.available_source_types_calls[0]
    assert "domain_knowledge" not in reviewer.available_source_types_calls[0]


def test_question_fingerprint_includes_objective():
    needs = [
        RuntimeResearchNeed(
            research_need_id="research_1",
            question="Vad gäller?",
            why_needed="behövs",
            source_types=["case_knowledge"],
        )
    ]
    left = question_fingerprint(needs, _objective("A"))
    right = question_fingerprint(needs, _objective("B"))
    assert left != right
    assert left == question_fingerprint(needs, _objective("A"))
