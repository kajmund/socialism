"""Iterative research loop: assess → follow-up wave → reassess → stop."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import ExecutionAttempt
from app.llm.research_followup import FollowUpPlanModel, LlmFollowUpPlanner
from app.services.execution import (
    get_attempt,
    get_evidence_set,
    list_evidence_items,
    list_need_executions,
    list_research_assessments,
    list_runtime_needs,
)
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
    programmatic_assessment,
)
from app.services.research.models import InvalidResearchPlanError, ResearchPlan, research_evidence
from app.services.research.execution import execute_attempt_research
from app.services.research.followup import (
    FollowUpNeedDraft,
    FollowUpPlannerError,
    RuntimeResearchNeed,
    research_question_key,
    validate_follow_up_drafts,
)
from app.services.research.models import (
    InvalidResearchPlanError,
    ResearchPlan,
    research_evidence,
)
from tests.test_research_assessment import RecordingAssessor, _fixed_draft
from tests.test_research_execution import (
    GuardRouter,
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


def _cite_existing_evidence(
    draft: ResearchAssessmentDraft,
    evidence: Sequence[AssessableEvidence],
) -> ResearchAssessmentDraft:
    """Stamp real EvidenceSet IDs so sanitize does not flip scripted sufficient."""
    if draft.result != "sufficient":
        return draft
    ids = [item.evidence_id for item in evidence]
    if not ids:
        return draft
    return ResearchAssessmentDraft(
        result=draft.result,
        rationale=draft.rationale,
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id=row.research_need_id,
                sufficient=row.sufficient,
                supporting_evidence_ids=row.supporting_evidence_ids or ids,
                missing_or_weak=row.missing_or_weak,
                contradictions=list(row.contradictions),
                further_information=row.further_information,
            )
            for row in draft.need_assessments
        ],
        gaps=list(draft.gaps),
        contradictions=list(draft.contradictions),
        considered_evidence_ids=list(draft.considered_evidence_ids) or ids,
        model_provider=draft.model_provider,
        model_name=draft.model_name,
        model_version=draft.model_version,
    )


class SequenceAssessor:
    def __init__(self, drafts: list[ResearchAssessmentDraft]) -> None:
        self.drafts = drafts
        self.calls: list[tuple[ResearchPlan, tuple[AssessableEvidence, ...]]] = []

    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        self.calls.append((plan, tuple(evidence)))
        draft = self.drafts[min(len(self.calls) - 1, len(self.drafts) - 1)]
        return _cite_existing_evidence(draft, evidence)


class ScriptedPlanner:
    def __init__(self, batches: list[list[FollowUpNeedDraft]]) -> None:
        self.batches = batches
        self.calls: list[tuple[ResearchPlan, ResearchAssessmentDraft, int]] = []

    async def plan_follow_ups(
        self,
        *,
        plan: ResearchPlan,
        assessment: ResearchAssessmentDraft,
        evidence: Sequence[AssessableEvidence],
        previous_needs: Sequence[RuntimeResearchNeed],
    ) -> Sequence[FollowUpNeedDraft]:
        self.calls.append((plan, assessment, len(previous_needs)))
        index = len(self.calls) - 1
        if index >= len(self.batches):
            return []
        return self.batches[index]


class BoomPlanner:
    async def plan_follow_ups(self, **_kwargs):
        raise RuntimeError("planner exploded")


def _follow_up(
    question: str,
    *,
    why: str = "lucka i bedömningen",
    source_types: list[str] | None = None,
    parent: str | None = "research_1",
    gap: str = "research_1: saknas",
) -> FollowUpNeedDraft:
    return FollowUpNeedDraft(
        question=question,
        why_needed=why,
        source_types=source_types or ["case_knowledge"],  # type: ignore[arg-type]
        parent_research_need_id=parent,
        source_gap=gap,
    )


@pytest.mark.asyncio
async def test_sufficient_after_initial_assessment_skips_planner(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-suff")
    planner = ScriptedPlanner([[_follow_up("Ska aldrig köras")]])
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        planner=planner,
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    rows = await list_research_assessments(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "sufficient"
    assert reloaded.research_wave == 0
    assert evidence_set.status == "frozen"
    assert planner.calls == []
    assert [row.assessment_pass for row in rows] == [1]
    assert rows[0].result == "sufficient"
    assert [row.origin for row in needs] == ["initial"]
    assert reloaded.research_plan_snapshot["needs"][0]["id"] == "research_1"


@pytest.mark.asyncio
async def test_follow_up_needs_are_persisted_before_retrieval(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-persist")
    attempt_id = attempt.id
    followup_started = asyncio.Event()
    release_followup = asyncio.Event()
    seen: dict[str, object] = {}

    class GateSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            if need.id != "research_1":
                followup_started.set()
                async with factory() as other:
                    seen["needs"] = await list_runtime_needs(other, attempt_id)
                    seen["executions"] = await list_need_executions(other, attempt_id)
                    row = await other.get(ExecutionAttempt, attempt_id)
                    seen["set"] = await get_evidence_set(other, row.evidence_set_id)
                    seen["items"] = await list_evidence_items(other, row.evidence_set_id)
                await release_followup.wait()
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="found",
                    excerpt=f"hit-{need.id}",
                    locator=need.id,
                )
            ]

    async def watch() -> None:
        await followup_started.wait()
        release_followup.set()

    watcher = asyncio.create_task(watch())
    assessor = SequenceAssessor(
        [
            _fixed_draft(
                result="insufficient",
                need_id="research_1",
                evidence_ids=[],
                further="Behöver taxa.",
            ),
            _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
        ]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(GateSource())[0],
        assessor=assessor,
        planner=ScriptedPlanner([[_follow_up("Vad är kommunens taxa?")]]),
    )
    await watcher
    derived = [row for row in seen["needs"] if row.origin == "derived"]
    assert result.status == "ready"
    assert derived
    assert derived[0].question == "Vad är kommunens taxa?"
    assert derived[0].wave_number == 1
    assert derived[0].parent_research_need_id == "research_1"
    assert derived[0].source_assessment_pass == 1
    assert seen["set"].status == "building"
    assert any(item.research_need_id == "research_1" for item in seen["items"])
    assert any(
        row.research_need_id == derived[0].research_need_id
        and row.status in {"pending", "running"}
        for row in seen["executions"]
    )


@pytest.mark.asyncio
async def test_derived_needs_use_same_bounded_async_machinery(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-conc")
    in_flight = 0
    max_in_flight = 0
    two_followups = asyncio.Event()
    release = asyncio.Event()

    class SlowSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            nonlocal in_flight, max_in_flight
            if need.id == "research_1":
                return [
                    research_evidence(
                        research_need_id=need.id,
                        source_type="case_knowledge",
                        status="found",
                        excerpt=f"hit-{need.id}",
                        locator=need.id,
                    )
                ]
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            if in_flight >= 2:
                two_followups.set()
            try:
                await release.wait()
                return [
                    research_evidence(
                        research_need_id=need.id,
                        source_type="case_knowledge",
                        status="found",
                        excerpt=f"hit-{need.id}",
                        locator=need.id,
                    )
                ]
            finally:
                in_flight -= 1

    exec_task = asyncio.create_task(
        execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=_router(SlowSource())[0],
            assessor=SequenceAssessor(
                [
                    _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[]),
                    _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
                ]
            ),
            planner=ScriptedPlanner(
                [
                    [
                        _follow_up("Första uppföljningen"),
                        _follow_up("Andra uppföljningen"),
                    ]
                ]
            ),
            concurrency=2,
        )
    )
    await asyncio.wait_for(two_followups.wait(), timeout=2)
    assert max_in_flight == 2
    release.set()
    await exec_task
    executions = await list_need_executions(session, attempt.id)
    assert len(executions) == 3
    assert all(row.status == "completed" for row in executions)
    assert max_in_flight == 2


@pytest.mark.asyncio
async def test_reassessment_sees_accumulated_evidence_then_freezes(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-accum")
    assessor = SequenceAssessor(
        [
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[]),
            _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
        ]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=assessor,
        planner=ScriptedPlanner([[_follow_up("Vad är kommunens taxa?")]]),
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    items = await list_evidence_items(session, evidence_set.id)
    rows = await list_research_assessments(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "sufficient"
    assert reloaded.research_wave == 1
    assert evidence_set.status == "frozen"
    assert len(assessor.calls) == 2
    first_ids = {item.evidence_id for item in assessor.calls[0][1]}
    second_ids = {item.evidence_id for item in assessor.calls[1][1]}
    assert first_ids < second_ids
    assert {item.research_need_id for item in items} == {
        "research_1",
        needs[1].research_need_id,
    }
    assert [row.assessment_pass for row in rows] == [1, 2]
    assert rows[0].result == "insufficient"
    assert rows[1].result == "sufficient"
    assert needs[0].origin == "initial"
    assert needs[1].origin == "derived"
    assert needs[1].parent_research_need_id == "research_1"
    assert reloaded.research_plan_snapshot["needs"] == [
        {
            "id": "research_1",
            "question": "Vad gäller skattesatsen?",
            "why_needed": "behövs för bedömning",
            "requested_by": ["legal"],
            "source_types": ["case_knowledge"],
        }
    ]


@pytest.mark.asyncio
async def test_max_iterations_stops_while_insufficient(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-max-i")
    planner = ScriptedPlanner(
        [
            [_follow_up("Uppföljning våg 1")],
            [_follow_up("Uppföljning våg 2")],
        ]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
        ),
        planner=planner,
        max_follow_up_waves=1,
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    rows = await list_research_assessments(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.status == "ready"
    assert reloaded.research_stop_reason == "max_iterations"
    assert reloaded.research_wave == 1
    assert evidence_set.status == "frozen"
    assert [row.result for row in rows] == ["insufficient", "insufficient"]
    assert len(planner.calls) == 1


@pytest.mark.asyncio
async def test_max_needs_cap_is_enforced(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-max-n")
    planner = ScriptedPlanner(
        [
            [
                _follow_up("Första extra"),
                _follow_up("Andra extra"),
                _follow_up("Tredje extra"),
            ]
        ]
    )
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
        ),
        planner=planner,
        max_follow_up_waves=3,
        max_needs=2,
    )
    reloaded = await get_attempt(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    executions = await list_need_executions(session, attempt.id)
    assert reloaded.research_stop_reason == "max_needs"
    assert reloaded.status == "ready"
    assert [row.origin for row in needs] == ["initial", "derived"]
    assert needs[1].question == "Första extra"
    assert len(executions) == 2


@pytest.mark.asyncio
async def test_initial_plan_over_need_limit_fails_closed_before_claim(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-over")
    with pytest.raises(InvalidResearchPlanError, match="research_max_needs_per_attempt=1"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(
                needs=[
                    _need("research_1", "case_knowledge"),
                    _need("research_2", "case_knowledge", question="Andra frågan?"),
                ]
            ),
            router=GuardRouter(),  # type: ignore[arg-type]
            max_needs=1,
        )
    reloaded = await session.get(ExecutionAttempt, attempt.id)
    assert reloaded is not None
    assert reloaded.status == "created"
    assert reloaded.started_at is None
    assert reloaded.evidence_set_id is None
    assert reloaded.research_stop_reason is None


@pytest.mark.asyncio
async def test_duplicate_follow_up_questions_are_not_reexecuted(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-dupe")
    source = RecordingSource("case_knowledge")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(source)[0],
        assessor=RecordingAssessor(
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
        ),
        planner=ScriptedPlanner(
            [[_follow_up("  VAD GÄLLER SKATTESATSEN?  ")]]
        ),
    )
    reloaded = await get_attempt(session, attempt.id)
    needs = await list_runtime_needs(session, attempt.id)
    executions = await list_need_executions(session, attempt.id)
    assert reloaded.research_stop_reason == "no_novel_followups"
    assert [row.origin for row in needs] == ["initial"]
    assert [row.research_need_id for row in executions] == ["research_1"]
    assert source.calls == 1


@pytest.mark.asyncio
async def test_no_novel_followups_stops_explicitly(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-none")
    planner = ScriptedPlanner([[]])
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge", mode="empty"))[0],
        assessor=RecordingAssessor(
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
        ),
        planner=planner,
    )
    reloaded = await get_attempt(session, attempt.id)
    rows = await list_research_assessments(session, attempt.id)
    assert reloaded.status == "ready"
    assert reloaded.research_stop_reason == "no_novel_followups"
    assert [row.result for row in rows] == ["insufficient"]
    assert len(planner.calls) == 1


@pytest.mark.asyncio
async def test_budget_exhaustion_is_not_infrastructure_failure(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-budget")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge", mode="empty"))[0],
        assessor=RecordingAssessor(
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
        ),
        planner=ScriptedPlanner([[_follow_up("Ny fråga")]]),
        max_follow_up_waves=0,
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    rows = await list_research_assessments(session, attempt.id)
    assert reloaded.status == "ready"
    assert evidence_set.status == "frozen"
    assert reloaded.research_stop_reason == "max_iterations"
    assert rows[0].result == "insufficient"


@pytest.mark.asyncio
async def test_planner_failure_is_fail_closed(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-boom-p")
    with pytest.raises(Exception, match="research failed"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=_router(RecordingSource("case_knowledge"))[0],
            assessor=RecordingAssessor(
                _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
            ),
            planner=BoomPlanner(),
        )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    assert reloaded.status == "failed"
    assert evidence_set.status == "failed"
    assert evidence_set.frozen_at is None
    assert reloaded.research_stop_reason is None


@pytest.mark.asyncio
async def test_second_pass_assessor_failure_does_not_freeze(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-boom-a")
    assessor = SequenceAssessor(
        [_fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])]
    )

    class BoomSecond:
        def __init__(self) -> None:
            self.calls = 0

        async def assess(self, plan, evidence):
            self.calls += 1
            if self.calls == 1:
                return assessor.drafts[0]
            raise RuntimeError("second assess exploded")

    with pytest.raises(Exception, match="research failed"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=_router(RecordingSource("case_knowledge"))[0],
            assessor=BoomSecond(),
            planner=ScriptedPlanner([[_follow_up("Ny fråga")]]),
        )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    rows = await list_research_assessments(session, attempt.id)
    assert reloaded.status == "failed"
    assert evidence_set.status == "failed"
    assert evidence_set.frozen_at is None
    assert [row.assessment_pass for row in rows] == [1]


@pytest.mark.asyncio
async def test_retry_does_not_duplicate_loop_state(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-idemp")
    assessor = SequenceAssessor(
        [
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[]),
            _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
        ]
    )
    planner = ScriptedPlanner([[_follow_up("Vad är kommunens taxa?")]])
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    router = _router(RecordingSource("case_knowledge"))[0]
    first = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        assessor=assessor,
        planner=planner,
    )
    second = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        assessor=assessor,
        planner=planner,
    )
    needs = await list_runtime_needs(session, attempt.id)
    rows = await list_research_assessments(session, attempt.id)
    items = await list_evidence_items(session, first.evidence_set_id)
    assert first.evidence_set_id == second.evidence_set_id
    assert len(assessor.calls) == 2
    assert len(planner.calls) == 1
    assert len(needs) == 2
    assert [row.assessment_pass for row in rows] == [1, 2]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_follow_up_keeps_run_tenant_scope(db):
    session, _factory = db
    customer, run, attempt = await _created_attempt(session, slug="loop-scope")
    source = RecordingSource("case_knowledge")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(source)[0],
        assessor=SequenceAssessor(
            [
                _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[]),
                _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
            ]
        ),
        planner=ScriptedPlanner([[_follow_up("Uppföljande scope?")]]),
    )
    assert source.calls == 2
    assert source.contexts[0].scope.customer_id == customer.id == run.customer_id
    assert source.contexts[1].scope.customer_id == customer.id
    assert source.contexts[1].scope.case_id == "case-1"
    assert source.contexts[1].scope.module == "dd"


@pytest.mark.asyncio
async def test_empty_plan_still_skips_planner(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="loop-empty")
    planner = ScriptedPlanner([[_follow_up("nej")]])
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(),
        router=GuardRouter(),  # type: ignore[arg-type]
        planner=planner,
    )
    reloaded = await get_attempt(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "sufficient"
    assert planner.calls == []


def test_question_key_is_case_and_whitespace_insensitive():
    assert research_question_key("  Vad gäller?  ") == research_question_key("vad gäller?")


def test_validate_follow_up_drafts_drops_duplicates_and_unknown_sources():
    previous = [
        RuntimeResearchNeed(
            research_need_id="research_1",
            question="Vad gäller skattesatsen?",
            why_needed="behövs",
            source_types=["case_knowledge"],
            origin="initial",
        )
    ]
    accepted = validate_follow_up_drafts(
        [
            _follow_up("Vad gäller skattesatsen?"),
            _follow_up("Ny fråga", source_types=["not_a_source"]),
            _follow_up("Ny giltig fråga"),
        ],
        previous_needs=previous,
        wave_number=1,
        assessment_pass=1,
    )
    assert [row.question for row in accepted] == ["Ny giltig fråga"]
    assert accepted[0].research_need_id == "followup_1_3"


@pytest.mark.asyncio
async def test_llm_planner_validates_structured_output():
    captured = []

    async def completer(messages, response_model):
        captured.append(response_model)
        return FollowUpPlanModel(
            needs=[
                {
                    "question": "Vad är taxa?",
                    "why_needed": "lucka",
                    "source_types": ["case_knowledge", "invented"],
                    "parent_research_need_id": "research_1",
                    "source_gap": "saknas",
                }
            ]
        )

    planner = LlmFollowUpPlanner(
        completer=completer,
        system_prompt="föreslå frågor",
        user_prompt=(
            "types {source_types}\n{plan_json}\n{assessment_json}\n"
            "{previous_needs_json}\n{evidence_json}"
        ),
    )
    drafts = await planner.plan_follow_ups(
        plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        assessment=programmatic_assessment(
            ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            [],
        ),
        evidence=[],
        previous_needs=[],
    )
    accepted = validate_follow_up_drafts(
        drafts,
        previous_needs=[],
        wave_number=1,
        assessment_pass=1,
    )
    assert captured == [FollowUpPlanModel]
    assert drafts[0].question == "Vad är taxa?"
    assert drafts[0].source_types == ["case_knowledge", "invented"]
    assert accepted == []


@pytest.mark.asyncio
async def test_llm_planner_failure_is_explicit():
    async def completer(messages, response_model):
        raise RuntimeError("model down")

    planner = LlmFollowUpPlanner(
        completer=completer,
        system_prompt="föreslå frågor",
        user_prompt=(
            "types {source_types}\n{plan_json}\n{assessment_json}\n"
            "{previous_needs_json}\n{evidence_json}"
        ),
    )
    with pytest.raises(FollowUpPlannerError):
        await planner.plan_follow_ups(
            plan=ResearchPlan(),
            assessment=programmatic_assessment(ResearchPlan(), []),
            evidence=[],
            previous_needs=[],
        )
