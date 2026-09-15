"""Persisted research progress events + reconnect catch-up."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import ResearchProgressEvent
from app.services.execution import (
    complete_need_execution,
    get_attempt,
    list_need_executions,
    seed_need_executions,
)
from app.services.research.completeness import ResearchCompletenessDraft
from app.services.research.execution import (
    ResearchExecutionError,
    execute_attempt_research,
)
from app.services.research.models import ResearchPlan, research_evidence
from app.services.research.planner import ResearchObjective
from app.services.research.progress import (
    append_research_progress_event,
    list_research_progress_events,
    sanitize_progress_payload,
)
from tests.test_research_assessment import RecordingAssessor, _fixed_draft
from tests.test_research_completeness import (
    SequenceCompletenessReviewer,
    _incomplete,
    _missing,
    _objective,
)
from tests.test_research_execution import (
    RaisingRouter,
    RecordingSource,
    _created_attempt,
    _need,
    _router,
)
from tests.test_research_loop import ScriptedPlanner, SequenceAssessor, _follow_up


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


def _types(events: list[ResearchProgressEvent]) -> list[str]:
    return [row.event_type for row in events]


def _payloads_are_small(events: list[ResearchProgressEvent]) -> None:
    blocked = {"prompt", "prompts", "messages", "chain_of_thought", "reasoning"}
    for row in events:
        payload = row.payload or {}
        assert blocked.isdisjoint(payload)
        assert "excerpt" not in payload
        assert "document" not in payload


@pytest.mark.asyncio
async def test_canonical_successful_run_emits_ordered_events(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="prog-ok")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=ResearchObjective(
            objective="Kartlägg kommunens skattesats", context={}
        ),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    events = await list_research_progress_events(session, attempt.id)
    assert result.status == "ready"
    assert [row.sequence for row in events] == list(range(1, len(events) + 1))
    assert _types(events) == [
        "objective_accepted",
        "initial_plan_accepted",
        "research_need_planned",
        "need_queued",
        "need_running",
        "evidence_found",
        "need_completed",
        "local_assessment_persisted",
        "global_completeness_persisted",
        "research_frozen_ready",
    ]
    assert events[5].payload["research_need_id"] == "research_1"
    assert events[5].payload["provider"] == "fake"
    assert events[8].payload["result"] == "complete"
    assert events[9].payload["stop_reason"] == "sufficient"
    _payloads_are_small(events)


@pytest.mark.asyncio
async def test_follow_up_and_global_cycle_stay_ordered(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="prog-waves")
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
    reviewer = SequenceCompletenessReviewer(
        [
            _incomplete(_missing("Vilka transaktioner skedde 2024?")),
            ResearchCompletenessDraft(
                result="complete",
                rationale="Målet är täckt.",
                model_provider="scripted",
                model_name="completeness-test",
            ),
        ]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=assessor,
        planner=ScriptedPlanner([[_follow_up("Vad är kommunens taxa?")]]),
        completeness_reviewer=reviewer,
        session_factory=factory,
    )
    events = await list_research_progress_events(session, attempt.id)
    types = _types(events)
    assert result.status == "ready"
    assert types.count("follow_up_need_derived") == 1
    assert types.count("global_need_derived") == 1
    assert types.count("local_assessment_persisted") == 3
    assert types.count("global_completeness_persisted") == 2
    assert types.index("follow_up_need_derived") < types.index("global_need_derived")
    assert types[-1] == "research_frozen_ready"
    assert [row.sequence for row in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_provider_error_and_capability_unavailable_are_accurate(db):
    session, factory = db
    _customer, _run, failed_attempt = await _created_attempt(session, slug="prog-err")
    with pytest.raises(ResearchExecutionError):
        await execute_attempt_research(
            session,
            attempt_id=failed_attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=RaisingRouter(),
        )
    failed_events = await list_research_progress_events(session, failed_attempt.id)
    assert "need_failed" in _types(failed_events)
    assert _types(failed_events)[-1] == "research_failed"
    reloaded = await get_attempt(session, failed_attempt.id)
    assert reloaded.status == "failed"

    _customer2, _run2, cap_attempt = await _created_attempt(session, slug="prog-cap")
    reviewer = SequenceCompletenessReviewer(
        [_incomplete(_missing("Vad säger skattelagen?", source_types=["swedish_law"]))]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=cap_attempt.id,
        research_objective=_objective(),
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        completeness_reviewer=reviewer,
        session_factory=factory,
    )
    cap_events = await list_research_progress_events(session, cap_attempt.id)
    assert result.status == "ready"
    assert "capability_unavailable" in _types(cap_events)
    assert "global_need_derived" not in _types(cap_events)
    cap = next(
        row for row in cap_events if row.event_type == "capability_unavailable"
    )
    assert "swedish_law" in cap.payload["unavailable_source_types"]
    assert _types(cap_events)[-1] == "research_frozen_ready"


@pytest.mark.asyncio
async def test_reconnect_after_sequence_returns_only_missed_events(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="prog-cursor")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    all_events = await list_research_progress_events(session, attempt.id)
    assert len(all_events) >= 4
    cursor = all_events[2].sequence
    missed = await list_research_progress_events(
        session, attempt.id, after_sequence=cursor
    )
    assert [row.sequence for row in missed] == [
        row.sequence for row in all_events if row.sequence > cursor
    ]
    assert missed[0].id == all_events[3].id


@pytest.mark.asyncio
async def test_duplicate_retry_does_not_emit_contradictory_transitions(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="prog-retry")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    first = await list_research_progress_events(session, attempt.id)
    second = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    again = await list_research_progress_events(session, attempt.id)
    assert second.status == "ready"
    assert [(row.id, row.sequence, row.event_type) for row in again] == [
        (row.id, row.sequence, row.event_type) for row in first
    ]

    executions = await list_need_executions(session, attempt.id)
    seeded = await seed_need_executions(
        session, attempt_id=attempt.id, need_ids=["research_1"]
    )
    completed = await complete_need_execution(session, executions[0].id)
    await append_research_progress_event(
        session,
        attempt_id=attempt.id,
        event_type="need_completed",
        idempotency_key="need_completed:research_1",
        payload={"research_need_id": "research_1", "need_execution_id": completed.id},
    )
    await session.commit()
    after_retry = await list_research_progress_events(session, attempt.id)
    assert len(after_retry) == len(first)
    assert seeded[0].id == executions[0].id


@pytest.mark.asyncio
async def test_worker_restart_preserves_event_history(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="prog-restart")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        session_factory=factory,
    )
    before = await list_research_progress_events(session, attempt.id)
    async with factory() as restarted:
        after = await list_research_progress_events(restarted, attempt.id)
    assert [(row.id, row.sequence, row.event_type) for row in after] == [
        (row.id, row.sequence, row.event_type) for row in before
    ]


@pytest.mark.asyncio
async def test_live_delivery_failure_does_not_roll_back_research(db, monkeypatch):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="prog-live")

    async def boom(_attempt_id: str, _event: dict) -> None:
        raise RuntimeError("socket down")

    monkeypatch.setattr(
        "app.realtime.research_progress_broadcast.research_progress_broadcast.publish",
        boom,
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    events = await list_research_progress_events(session, attempt.id)
    assert result.status == "ready"
    assert _types(events)[-1] == "research_frozen_ready"
    missed = await list_research_progress_events(session, attempt.id, after_sequence=2)
    assert missed[0].sequence == 3


@pytest.mark.asyncio
async def test_evidence_error_status_is_projected(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="prog-ev-err")

    class ErrorSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need, context):
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="error",
                    provider="fake",
                    excerpt="source failed",
                )
            ]

    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(ErrorSource())[0],
    )
    events = await list_research_progress_events(session, attempt.id)
    assert result.status == "ready"
    assert "evidence_error" in _types(events)
    assert "research_failed" not in _types(events)


def test_sanitize_progress_payload_strips_prompts():
    clean = sanitize_progress_payload(
        {
            "research_need_id": "n1",
            "prompt": "SYSTEM: tänk steg för steg",
            "messages": [{"role": "user", "content": "x"}],
            "chain_of_thought": "hemlig reasoning",
            "nested": {"reasoning": "nope", "source_type": "case_knowledge"},
        }
    )
    assert clean == {
        "research_need_id": "n1",
        "nested": {"source_type": "case_knowledge"},
    }
