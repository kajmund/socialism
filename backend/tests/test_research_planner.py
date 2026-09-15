"""Research objective → ResearchPlanner → validated initial ResearchPlan."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import ExecutionAttempt
from app.llm.research_planner import LlmResearchPlanner, PlannedResearchModel
from app.services.execution import (
    get_attempt,
    list_evidence_items,
    list_need_executions,
    list_research_assessments,
    list_runtime_needs,
    set_attempt_snapshots,
)
from app.services.prompt_catalog import default_prompts, render_prompt
from app.services.research.execution import execute_attempt_research
from app.services.research.followup import FollowUpNeedDraft
from app.services.research.models import (
    InvalidResearchPlanError,
    ResearchPlan,
    research_evidence,
)
from app.services.research.plan import research_plan_to_snapshot
from app.services.research.planner import (
    FakeResearchPlanner,
    InvalidResearchObjectiveError,
    ResearchNeedDraft,
    ResearchObjective,
    ResearchPlannerError,
    plan_from_planner_drafts,
    require_research_objective,
)
from app.services.research.registry import (
    ResearchSourceRegistry,
    production_registered_source_types,
)
from app.services.research.router import ResearchRouter
from tests.test_research_assessment import _fixed_draft
from tests.test_research_execution import (
    RecordingSource,
    _created_attempt,
    _need,
    _router,
)
from tests.test_research_loop import ScriptedPlanner, SequenceAssessor


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


def _draft(
    question: str = "Vad gäller skattesatsen?",
    *,
    why: str = "behövs för bedömning",
    source_types: list[str] | None = None,
    proposed_id: str = "",
) -> ResearchNeedDraft:
    return ResearchNeedDraft(
        question=question,
        why_needed=why,
        source_types=["case_knowledge"] if source_types is None else source_types,  # type: ignore[arg-type]
        proposed_id=proposed_id,
    )


def _objective(text: str = "Vad är kommunens skattesats?", **context) -> ResearchObjective:
    return ResearchObjective(objective=text, context=dict(context))


@pytest.mark.asyncio
async def test_generated_plan_persists_before_any_retrieval(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-persist")
    attempt_id = attempt.id
    seen: dict[str, object] = {}

    class GateSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            async with factory() as other:
                row = await other.get(ExecutionAttempt, attempt_id)
                seen["status"] = row.status
                seen["objective"] = row.research_objective_snapshot
                seen["plan"] = row.research_plan_snapshot
                seen["items"] = await list_evidence_items(other, row.evidence_set_id)
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="found",
                    excerpt="skattesats 32%",
                    locator="p1",
                )
            ]

    router, _ = _router(GateSource())
    planner = FakeResearchPlanner([_draft(proposed_id="research_1")])
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_planner=planner,
        router=router,
    )
    reloaded = await get_attempt(session, attempt.id)
    assert result.status == "ready"
    assert planner.calls
    assert reloaded.research_objective_snapshot["objective"] == (
        "Vad är kommunens skattesats?"
    )
    assert reloaded.research_plan_snapshot["needs"][0]["id"] == "research_1"
    assert reloaded.research_plan_snapshot["needs"][0]["question"] == (
        "Vad gäller skattesatsen?"
    )
    assert seen["status"] == "researching"
    assert seen["objective"]["objective"] == "Vad är kommunens skattesats?"
    assert seen["plan"]["needs"][0]["id"] == "research_1"
    assert seen["items"] == []


@pytest.mark.asyncio
async def test_planner_failure_leaves_research_unstarted(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-fail")

    class BoomPlanner:
        async def plan_research(self, *, objective, available_source_types=None):
            raise RuntimeError("model down")

    with pytest.raises(ResearchPlannerError, match="planning failed"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=BoomPlanner(),
            router=_router(RecordingSource("case_knowledge"))[0],
        )
    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.status == "created"
    assert reloaded.research_plan_snapshot is None
    assert reloaded.evidence_set_id is None
    assert await list_need_executions(session, attempt.id) == []
    assert await list_runtime_needs(session, attempt.id) == []


@pytest.mark.asyncio
async def test_invalid_duplicate_and_over_budget_plans_fail_closed(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-invalid")
    router, sources = _router(RecordingSource("case_knowledge"))

    with pytest.raises(InvalidResearchPlanError, match="Duplicate"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=FakeResearchPlanner(
                [
                    _draft("Vad gäller skattesatsen?"),
                    _draft("  vad gäller SKATTESATSEN?  "),
                ]
            ),
            router=router,
        )
    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.status == "created"
    assert reloaded.research_plan_snapshot is None
    assert sources[0].calls == 0

    with pytest.raises(InvalidResearchPlanError, match="unavailable source_type"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=FakeResearchPlanner(
                [_draft(source_types=["not_a_source"])]
            ),
            router=router,
        )

    with pytest.raises(InvalidResearchPlanError, match="research_max_needs_per_attempt=1"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=FakeResearchPlanner(
                [_draft("Första?"), _draft("Andra?")]
            ),
            router=router,
            max_needs=1,
        )
    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.status == "created"
    assert reloaded.evidence_set_id is None
    assert sources[0].calls == 0


@pytest.mark.asyncio
async def test_retry_does_not_regenerate_plan_after_snapshot(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-retry")
    frozen = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    await set_attempt_snapshots(
        session,
        attempt_id=attempt.id,
        research_objective_snapshot={
            "objective": "Vad är kommunens skattesats?",
            "context": {},
        },
        research_plan_snapshot=research_plan_to_snapshot(frozen),
    )
    planner = FakeResearchPlanner([_draft("Helt annan fråga?")])
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_planner=planner,
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    reloaded = await get_attempt(session, attempt.id)
    assert result.status == "ready"
    assert planner.calls == []
    assert reloaded.research_plan_snapshot["needs"][0]["question"] == (
        "Vad gäller skattesatsen?"
    )


@pytest.mark.asyncio
async def test_tenant_scope_comes_from_run_not_objective_context(db):
    session, _factory = db
    customer, run, attempt = await _created_attempt(session, slug="plan-scope")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(customer_id=999, case_id="injected"),
        research_planner=FakeResearchPlanner([_draft()]),
        router=router,
    )
    assert source.contexts
    assert source.contexts[0].scope.customer_id == customer.id
    assert source.contexts[0].scope.case_id == "case-1"
    assert source.contexts[0].scope.module == run.module


@pytest.mark.asyncio
async def test_generated_plan_flows_unchanged_into_research_loop(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-loop")
    follow_up = ScriptedPlanner(
        [
            [
                FollowUpNeedDraft(
                    question="Vad är kommunens taxa?",
                    why_needed="lucka i bedömningen",
                    source_types=["case_knowledge"],
                    parent_research_need_id="research_1",
                    source_gap="research_1: saknas",
                )
            ]
        ]
    )
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
        research_objective=_objective(),
        research_planner=FakeResearchPlanner(
            [_draft("Vad gäller skattesatsen?", proposed_id="research_1")]
        ),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=assessor,
        planner=follow_up,
    )
    reloaded = await get_attempt(session, attempt.id)
    runtime = await list_runtime_needs(session, attempt.id)
    rows = await list_research_assessments(session, attempt.id)
    snapshot_ids = [need["id"] for need in reloaded.research_plan_snapshot["needs"]]
    assert result.status == "ready"
    assert snapshot_ids == ["research_1"]
    assert [row.origin for row in runtime] == ["initial", "derived"]
    assert runtime[0].question == "Vad gäller skattesatsen?"
    assert runtime[1].question == "Vad är kommunens taxa?"
    assert reloaded.research_stop_reason == "sufficient"
    assert [row.assessment_pass for row in rows] == [1, 2]
    assert follow_up.calls[0][0].needs[0].id == "research_1"
    assert follow_up.calls[0][0].needs[0].question == "Vad gäller skattesatsen?"


@pytest.mark.asyncio
async def test_empty_and_trivial_objectives_are_rejected(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-empty")
    router, sources = _router(RecordingSource("case_knowledge"))
    with pytest.raises(InvalidResearchObjectiveError, match="concrete"):
        require_research_objective("   ")
    with pytest.raises(InvalidResearchObjectiveError, match="concrete"):
        ResearchObjective(objective="...")
    with pytest.raises(InvalidResearchObjectiveError, match="required"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            router=router,
        )
    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.status == "created"
    assert reloaded.research_plan_snapshot is None
    assert sources[0].calls == 0


@pytest.mark.asyncio
async def test_explicit_plan_skips_research_planner(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-explicit")
    planner = FakeResearchPlanner([_draft("Ska aldrig användas")])
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        research_planner=planner,
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    assert result.status == "ready"
    assert planner.calls == []


def test_planner_user_prompt_is_rendered_at_call_time():
    prompts = default_prompts("sv")
    with pytest.raises(RuntimeError, match="missing placeholder"):
        render_prompt(prompts, "research.planner.user")
    rendered = render_prompt(
        prompts,
        "research.planner.user",
        source_types="case_knowledge",
        objective="Vad är skattesatsen?",
        objective_json='{"objective":"Vad är skattesatsen?"}',
        context_json="{}",
    )
    assert "Vad är skattesatsen?" in rendered
    assert "case_knowledge" in rendered


@pytest.mark.asyncio
async def test_llm_planner_uses_injected_prompt_and_objective_data():
    captured: list[list[dict]] = []

    async def completer(messages, response_model):
        captured.append(messages)
        assert response_model is PlannedResearchModel
        return PlannedResearchModel.model_validate(
            {
                "needs": [
                    {
                        "id": "research_1",
                        "question": "Vad gäller skattesatsen?",
                        "why_needed": "behövs",
                        "source_types": ["case_knowledge"],
                    }
                ]
            }
        )

    planner = LlmResearchPlanner(
        completer=completer,
        system_prompt="Bryt ner målet.",
        user_prompt="OVERRIDE {objective} :: {context_json} :: {source_types}",
        source_types=["case_knowledge", "customer_knowledge"],
    )
    drafts = await planner.plan_research(
        objective=_objective("Vad är skattesatsen?", matter="tax")
    )
    assert drafts[0].question == "Vad gäller skattesatsen?"
    assert drafts[0].why_needed == "behövs"
    user = captured[0][1]["content"]
    assert user.startswith("OVERRIDE Vad är skattesatsen?")
    assert '"matter": "tax"' in user
    assert "case_knowledge" in user


@pytest.mark.asyncio
async def test_llm_planner_parse_failure_raises(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-parse")

    async def completer(messages, response_model):
        raise ValueError("not json")

    planner = LlmResearchPlanner(
        completer=completer,
        system_prompt="Bryt ner målet.",
        user_prompt="Mål: {objective} {objective_json} {context_json} {source_types}",
        source_types=["case_knowledge", "customer_knowledge"],
    )
    with pytest.raises(ResearchPlannerError, match="model call failed"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=planner,
            router=_router(RecordingSource("case_knowledge"))[0],
        )
    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.status == "created"
    assert reloaded.research_plan_snapshot is None


def test_plan_from_planner_drafts_assigns_ids_and_rejects_gaps():
    plan = plan_from_planner_drafts(
        [_draft("Första frågan?"), _draft("Andra frågan?", proposed_id="custom")]
    )
    assert [need.id for need in plan.needs] == ["research_1", "custom"]
    with pytest.raises(InvalidResearchPlanError, match="why_needed"):
        plan_from_planner_drafts([_draft(why="  ")])
    with pytest.raises(InvalidResearchPlanError, match="source_types"):
        plan_from_planner_drafts([_draft(source_types=[])])
    with pytest.raises(InvalidResearchPlanError, match="at least one need"):
        plan_from_planner_drafts([])


@pytest.mark.asyncio
async def test_generated_empty_plan_fails_closed(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-empty-gen")
    router, sources = _router(RecordingSource("case_knowledge"))
    planner = FakeResearchPlanner([])
    with pytest.raises(InvalidResearchPlanError, match="at least one need"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=planner,
            router=router,
        )
    reloaded = await get_attempt(session, attempt.id)
    assert planner.calls
    assert reloaded.status == "created"
    assert reloaded.research_plan_snapshot is None
    assert reloaded.evidence_set_id is None
    assert await list_need_executions(session, attempt.id) == []
    assert await list_runtime_needs(session, attempt.id) == []
    assert await list_research_assessments(session, attempt.id) == []
    assert sources[0].calls == 0


@pytest.mark.asyncio
async def test_generated_plan_rejects_source_types_router_cannot_run(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-unreg")
    router, sources = _router(RecordingSource("case_knowledge"))
    planner = FakeResearchPlanner([_draft(source_types=["swedish_law"])])
    with pytest.raises(InvalidResearchPlanError, match="unavailable source_type"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=planner,
            router=router,
        )
    reloaded = await get_attempt(session, attempt.id)
    assert planner.available_source_types_calls == [("case_knowledge",)]
    assert reloaded.status == "created"
    assert reloaded.research_plan_snapshot is None
    assert reloaded.evidence_set_id is None
    assert await list_need_executions(session, attempt.id) == []
    assert sources[0].calls == 0


@pytest.mark.asyncio
async def test_llm_planner_is_offered_only_executable_source_types():
    captured: list[list[dict]] = []

    async def completer(messages, response_model):
        captured.append(messages)
        return PlannedResearchModel.model_validate(
            {
                "needs": [
                    {
                        "question": "Vad gäller skattesatsen?",
                        "why_needed": "behövs",
                        "source_types": ["case_knowledge"],
                    }
                ]
            }
        )

    planner = LlmResearchPlanner(
        completer=completer,
        system_prompt="Bryt ner målet.",
        user_prompt="Tillåtna: {source_types}",
        source_types=production_registered_source_types(),
    )
    await planner.plan_research(
        objective=_objective(),
        available_source_types=("case_knowledge",),
    )
    offered = captured[0][1]["content"]
    assert offered == "Tillåtna: case_knowledge"
    assert "swedish_law" not in offered
    assert "swedish_preparatory_works" not in offered
    assert "web" not in offered
    assert "domain_knowledge" not in offered


def test_production_registered_source_types_match_standard_registry():
    types = production_registered_source_types()
    assert types == ("case_knowledge", "customer_knowledge")
    assert "swedish_law" not in types
    assert "web" not in types


def test_llm_planner_rejects_empty_source_types():
    with pytest.raises(ResearchPlannerError, match="no executable"):
        LlmResearchPlanner(
            system_prompt="Bryt ner målet.",
            user_prompt="Tillåtna: {source_types}",
            source_types=(),
        )


@pytest.mark.asyncio
async def test_planner_fails_closed_when_router_has_no_sources(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="plan-nosrc")
    planner = FakeResearchPlanner([_draft()])
    with pytest.raises(ResearchPlannerError, match="no executable"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_planner=planner,
            router=ResearchRouter(ResearchSourceRegistry()),
        )
    reloaded = await get_attempt(session, attempt.id)
    assert planner.calls == []
    assert reloaded.status == "created"
    assert reloaded.research_plan_snapshot is None
