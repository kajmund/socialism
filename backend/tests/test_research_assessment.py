"""Evidence sufficiency assessment after the initial ResearchNeed barrier."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import EvidenceSet, ExecutionAttempt, ResearchAssessment
from app.llm.research_assessment import (
    EvidenceSufficiencyModel,
    LlmResearchAssessor,
    NeedSufficiencyModel,
)
from app.services.execution import (
    get_attempt,
    get_evidence_set,
    get_research_assessment,
    list_evidence_items,
    list_need_executions,
    list_research_assessments,
)
from app.services.prompt_catalog import default_prompts, render_prompt
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
    ResearchAssessmentError,
    ResearchNeedAssessment,
    can_assess_programmatically,
    evidence_fingerprint,
    programmatic_assessment,
    sanitize_assessment_draft,
)
from app.services.research.execution import execute_attempt_research
from app.services.research.models import ResearchPlan, research_evidence
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


class RecordingAssessor:
    def __init__(self, draft: ResearchAssessmentDraft | None = None) -> None:
        self.calls: list[tuple[ResearchPlan, tuple[AssessableEvidence, ...]]] = []
        self.draft = draft

    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        self.calls.append((plan, tuple(evidence)))
        if self.draft is not None:
            return self.draft
        return programmatic_assessment(plan, evidence)


class BoomAssessor:
    async def assess(self, plan: ResearchPlan, evidence: Sequence[AssessableEvidence]):
        raise RuntimeError("model exploded")


def _fixed_draft(
    *,
    result: str,
    need_id: str,
    evidence_ids: list[str],
    further: str | None = None,
) -> ResearchAssessmentDraft:
    return ResearchAssessmentDraft(
        result=result,  # type: ignore[arg-type]
        rationale="scripted",
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id=need_id,
                sufficient=result == "sufficient",
                supporting_evidence_ids=evidence_ids,
                missing_or_weak="" if result == "sufficient" else "saknas",
                contradictions=["källa A vs B"] if result == "insufficient" else [],
                further_information=further,
            )
        ],
        gaps=[] if result == "sufficient" else ["research_1: saknas"],
        contradictions=["osäkerhet i utdrag"] if result == "insufficient" else [],
        considered_evidence_ids=evidence_ids,
        model_provider="fake",
        model_name="scripted",
        model_version="v1",
    )


@pytest.mark.asyncio
async def test_assessment_runs_only_after_need_executions_complete(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-barrier")
    attempt_id = attempt.id
    release_slow = asyncio.Event()
    fast_retrieving = asyncio.Event()
    assessor = RecordingAssessor()

    class SplitSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            if need.id == "fast":
                fast_retrieving.set()
            if need.id == "slow":
                await release_slow.wait()
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
        await fast_retrieving.wait()
        while True:
            async with factory() as other:
                row = await other.get(ExecutionAttempt, attempt_id)
                if row is not None and row.evidence_set_id:
                    items = await list_evidence_items(other, row.evidence_set_id)
                    if any(item.research_need_id == "fast" for item in items):
                        assert assessor.calls == []
                        existing = await other.execute(
                            select(ResearchAssessment).where(
                                ResearchAssessment.attempt_id == attempt_id
                            )
                        )
                        assert existing.scalars().first() is None
                        assert (await other.get(EvidenceSet, row.evidence_set_id)).status == (
                            "building"
                        )
                        return
            await asyncio.sleep(0.01)

    router, _ = _router(SplitSource())
    watch_task = asyncio.create_task(watch())
    exec_task = asyncio.create_task(
        execute_attempt_research(
            session,
            attempt_id=attempt_id,
            research_plan=ResearchPlan(
                needs=[
                    _need("fast", "case_knowledge"),
                    _need("slow", "case_knowledge"),
                ]
            ),
            router=router,
            assessor=assessor,
            session_factory=factory,
            concurrency=2,
        )
    )
    await asyncio.wait_for(watch_task, timeout=2)
    assert assessor.calls == []
    release_slow.set()
    result = await exec_task
    assert result.status == "ready"
    assert len(assessor.calls) == 1
    plan, evidence = assessor.calls[0]
    assert {need.id for need in plan.needs} == {"fast", "slow"}
    assert {item.research_need_id for item in evidence} == {"fast", "slow"}


@pytest.mark.asyncio
async def test_assessor_sees_persisted_evidence_not_live_results(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-persisted")
    assessor = RecordingAssessor()
    live_only = "not-persisted-secret"
    source = RecordingSource("case_knowledge", excerpt=f"skattesats 32% {live_only}")
    router, _ = _router(source)
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
        assessor=assessor,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    assert len(assessor.calls) == 1
    _plan, evidence = assessor.calls[0]
    assert [item.evidence_id for item in evidence] == [
        item.original_evidence_id or item.id for item in items
    ]
    assert evidence[0].excerpt == items[0].excerpt
    assert evidence[0].source_id == items[0].source_id
    assert evidence[0].locator == items[0].locator
    assert evidence[0].provider == items[0].provider
    assert evidence[0].score == items[0].score


@pytest.mark.asyncio
async def test_sufficient_assessment_persists_then_freezes_ready(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-ok")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        assessor=RecordingAssessor(),
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    evidence_id = items[0].original_evidence_id
    row = await get_research_assessment(session, attempt.id)
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    assert result.status == "ready"
    assert reloaded.status == "ready"
    assert evidence_set.status == "frozen"
    assert row is not None
    assert row.result == "sufficient"
    assert row.attempt_id == attempt.id
    assert row.evidence_set_id == result.evidence_set_id
    assert evidence_id in row.considered_evidence_ids
    assert row.need_assessments[0]["research_need_id"] == "research_1"
    assert row.need_assessments[0]["sufficient"] is True
    assert evidence_id in row.need_assessments[0]["supporting_evidence_ids"]


@pytest.mark.asyncio
async def test_insufficient_assessment_still_freezes_ready_in_v1(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-gap")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    assessor = RecordingAssessor(
        _fixed_draft(
            result="insufficient",
            need_id="research_1",
            evidence_ids=[],
            further="Behöver kommunens taxa.",
        )
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
        assessor=assessor,
    )
    row = await get_research_assessment(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    reloaded = await get_attempt(session, attempt.id)
    assert result.status == "ready"
    assert reloaded.status == "ready"
    assert evidence_set.status == "frozen"
    assert row is not None
    assert row.result == "insufficient"
    assert row.need_assessments[0]["sufficient"] is False
    assert row.need_assessments[0]["further_information"] == "Behöver kommunens taxa."
    assert row.gaps == ["research_1: saknas"]
    assert row.contradictions == ["osäkerhet i utdrag"]
    assert row.need_assessments[0]["contradictions"] == ["källa A vs B"]


@pytest.mark.asyncio
async def test_assessor_failure_is_fail_closed(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-boom")
    router, _ = _router(RecordingSource("case_knowledge"))
    with pytest.raises(Exception, match="research failed"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=router,
            assessor=BoomAssessor(),
        )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    assert reloaded.status == "failed"
    assert evidence_set.status == "failed"
    assert evidence_set.frozen_at is None
    assert await get_research_assessment(session, attempt.id) is None


@pytest.mark.asyncio
async def test_retry_finalization_does_not_duplicate_assessment(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-idemp")
    assessor = RecordingAssessor()
    router, _ = _router(RecordingSource("case_knowledge"))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    first = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        assessor=assessor,
    )
    second = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        assessor=assessor,
    )
    rows = await list_research_assessments(session, attempt.id)
    assert first.evidence_set_id == second.evidence_set_id
    assert len(assessor.calls) == 1
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_empty_plan_is_sufficient_without_llm(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-empty")
    calls = []

    async def completer(messages, response_model):
        calls.append(response_model)
        raise AssertionError("empty plan must not call the model")

    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(),
        router=GuardRouter(),  # type: ignore[arg-type]
        assessor=LlmResearchAssessor(
            completer=completer,
            system_prompt="bedöm evidens",
            user_prompt="ResearchPlan:\n{plan_json}\n\nEvidenceSet:\n{evidence_json}",
            provider="cerebras",
            model="unused",
        ),
    )
    row = await get_research_assessment(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    assert result.status == "ready"
    assert calls == []
    assert row is not None
    assert row.result == "sufficient"
    assert row.need_assessments == []
    assert row.model_provider == "programmatic"
    assert evidence_set.status == "frozen"


@pytest.mark.asyncio
async def test_empty_evidence_with_needs_is_insufficient_without_llm(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-no-hits")
    calls = []

    async def completer(messages, response_model):
        calls.append(response_model)
        raise AssertionError("no-found evidence must not call the model")

    router, _ = _router(RecordingSource("case_knowledge", mode="empty"))
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
        assessor=LlmResearchAssessor(
            completer=completer,
            system_prompt="bedöm evidens",
            user_prompt="ResearchPlan:\n{plan_json}\n\nEvidenceSet:\n{evidence_json}",
        ),
    )
    row = await get_research_assessment(session, attempt.id)
    assert result.status == "ready"
    assert calls == []
    assert row is not None
    assert row.result == "insufficient"
    assert row.need_assessments[0]["sufficient"] is False
    assert row.need_assessments[0]["further_information"] == "Vad gäller skattesatsen?"


def test_invalid_evidence_ids_are_discarded():
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    evidence = [
        AssessableEvidence(
            evidence_id="real-1",
            research_need_id="research_1",
            source_type="case_knowledge",
            status="found",
            title="T",
            excerpt="skatt",
            locator="p1",
            source_id="doc",
            source_url="https://example.test",
            provider="fake",
            score=0.5,
            provenance={"document_id": "doc"},
            retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
            content_hash="abc",
        )
    ]
    draft = ResearchAssessmentDraft(
        result="sufficient",
        rationale="påhittade källor",
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id="research_1",
                sufficient=True,
                supporting_evidence_ids=["real-1", "hallucinated-99"],
            )
        ],
        considered_evidence_ids=["real-1", "hallucinated-99"],
    )
    cleaned = sanitize_assessment_draft(draft, plan=plan, evidence=evidence)
    assert cleaned.considered_evidence_ids == ["real-1"]
    assert cleaned.need_assessments[0].supporting_evidence_ids == ["real-1"]
    assert cleaned.result == "sufficient"

    invented_only = ResearchAssessmentDraft(
        result="sufficient",
        rationale="bara påhitt",
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id="research_1",
                sufficient=True,
                supporting_evidence_ids=["hallucinated-99"],
            )
        ],
        considered_evidence_ids=["hallucinated-99"],
    )
    closed = sanitize_assessment_draft(invented_only, plan=plan, evidence=evidence)
    assert closed.result == "insufficient"
    assert closed.need_assessments[0].sufficient is False
    assert closed.need_assessments[0].supporting_evidence_ids == []
    assert closed.considered_evidence_ids == ["real-1"]

    uncited = ResearchAssessmentDraft(
        result="sufficient",
        rationale="inga citat",
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id="research_1",
                sufficient=True,
                supporting_evidence_ids=[],
            )
        ],
    )
    rejected = sanitize_assessment_draft(uncited, plan=plan, evidence=evidence)
    assert rejected.result == "insufficient"
    assert rejected.need_assessments[0].sufficient is False
    assert rejected.need_assessments[0].supporting_evidence_ids == []
    assert (
        "cite persisted EvidenceSet IDs"
        in rejected.need_assessments[0].missing_or_weak
    )


def test_assessment_user_prompt_is_rendered_at_call_time():
    prompts = default_prompts("sv")
    with pytest.raises(RuntimeError, match="missing placeholder"):
        render_prompt(prompts, "research.assessment.user")
    rendered = render_prompt(
        prompts,
        "research.assessment.user",
        plan_json='{"needs":[]}',
        evidence_json="[]",
    )
    assert '{"needs":[]}' in rendered
    assert "EvidenceSet:" in rendered


@pytest.mark.asyncio
async def test_llm_assessor_sanitizes_structured_output():
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    evidence = [
        AssessableEvidence(
            evidence_id="real-1",
            research_need_id="research_1",
            source_type="case_knowledge",
            status="found",
            title="T",
            excerpt="skatt",
            locator="p1",
            source_id="doc",
            source_url=None,
            provider="fake",
            score=0.9,
            provenance={},
            retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
            content_hash="abc",
        )
    ]

    async def completer(messages, response_model):
        assert response_model is EvidenceSufficiencyModel
        assert "real-1" in messages[-1]["content"]
        return EvidenceSufficiencyModel(
            result="sufficient",
            rationale="stöds",
            need_assessments=[
                NeedSufficiencyModel(
                    research_need_id="research_1",
                    sufficient=True,
                    supporting_evidence_ids=["real-1", "nope"],
                )
            ],
            considered_evidence_ids=["real-1", "nope"],
        )

    assessor = LlmResearchAssessor(
        completer=completer,
        system_prompt="bedöm evidens",
        user_prompt="ResearchPlan:\n{plan_json}\n\nEvidenceSet:\n{evidence_json}",
        provider="cerebras",
        model="gpt-oss-120b",
    )
    draft = await assessor.assess(plan, evidence)
    assert draft.result == "sufficient"
    assert draft.considered_evidence_ids == ["real-1"]
    assert draft.need_assessments[0].supporting_evidence_ids == ["real-1"]
    assert draft.model_provider == "cerebras"
    assert draft.model_name == "gpt-oss-120b"


@pytest.mark.asyncio
async def test_llm_parse_failure_raises_assessment_error():
    async def completer(messages, response_model):
        raise ValueError("not json")

    assessor = LlmResearchAssessor(
        completer=completer,
        system_prompt="bedöm evidens",
        user_prompt="ResearchPlan:\n{plan_json}\n\nEvidenceSet:\n{evidence_json}",
    )
    with pytest.raises(ResearchAssessmentError, match="model call failed"):
        await assessor.assess(
            ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            [
                AssessableEvidence(
                    evidence_id="real-1",
                    research_need_id="research_1",
                    source_type="case_knowledge",
                    status="found",
                    title=None,
                    excerpt="hit",
                    locator=None,
                    source_id=None,
                    source_url=None,
                    provider=None,
                    score=None,
                    provenance={},
                    retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
                    content_hash="abc",
                )
            ],
        )


def test_programmatic_empty_and_found_semantics():
    empty = programmatic_assessment(ResearchPlan(), [])
    assert empty.result == "sufficient"
    assert can_assess_programmatically(ResearchPlan(), []) is True

    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    missing = programmatic_assessment(plan, [])
    assert missing.result == "insufficient"
    assert can_assess_programmatically(plan, []) is True

    found = AssessableEvidence(
        evidence_id="e1",
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        title=None,
        excerpt="hit",
        locator=None,
        source_id=None,
        source_url=None,
        provider=None,
        score=None,
        provenance={},
        retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
        content_hash="h1",
    )
    assert can_assess_programmatically(plan, [found]) is False
    ok = programmatic_assessment(plan, [found])
    assert ok.result == "sufficient"
    assert evidence_fingerprint([found]) == evidence_fingerprint([found])


@pytest.mark.asyncio
async def test_need_executions_completed_before_assessment_uses_all_items(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="assess-all")
    assessor = RecordingAssessor()
    router, _ = _router(RecordingSource("case_knowledge"))
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(
            needs=[
                _need("research_1", "case_knowledge"),
                _need("research_2", "case_knowledge"),
            ]
        ),
        router=router,
        assessor=assessor,
        concurrency=2,
    )
    executions = await list_need_executions(session, attempt.id)
    assert {row.status for row in executions} == {"completed"}
    _plan, evidence = assessor.calls[0]
    assert len(evidence) == 2
