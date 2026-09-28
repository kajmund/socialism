"""Need-deadline tests extracted from test_research_execution."""

from __future__ import annotations

import asyncio

import pytest

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.services.execution import (
    get_attempt,
    get_evidence_set,
    get_research_assessment,
    list_evidence_items,
    list_need_executions,
)
from app.services.research import (
    ResearchPlan,
    execute_attempt_research,
)
from app.services.research.assessment import ProgrammaticResearchAssessor
from app.services.research.execution import _complete_timed_out_need, assessable_from_item
from app.services.research.models import ResearchContext, ResearchNeed
from app.services.research.progress import list_research_progress_events
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


class HangingRouter:
    async def execute_need(self, need: ResearchNeed, context: ResearchContext):
        del need, context
        await asyncio.sleep(30)

    def available_source_types(self) -> tuple[str, ...]:
        return ()


class MixedTimeoutRouter:
    """Hang one need; retrieve found evidence for the other."""

    def __init__(self, hang_need_id: str, source: RecordingSource) -> None:
        self.hang_need_id = hang_need_id
        self.source = source

    async def execute_need(self, need: ResearchNeed, context: ResearchContext):
        if need.id == self.hang_need_id:
            await asyncio.sleep(30)
            return []
        return await self.source.research(need, context)

    def available_source_types(self) -> tuple[str, ...]:
        return (self.source.source_type,)


@pytest.mark.asyncio
async def test_need_deadline_fails_the_need_and_the_attempt(db, monkeypatch):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="deadline-co")
    monkeypatch.setattr(settings, "research_need_timeout_seconds", 0.05)
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_5", "case_knowledge")]),
        router=HangingRouter(),  # type: ignore[arg-type]
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    executions = await list_need_executions(session, attempt.id)
    events = await list_research_progress_events(session, attempt.id)
    items = await list_evidence_items(session, evidence_set.id)
    assert result.status == "ready"
    assert reloaded.status == "ready"
    assert evidence_set.status == "frozen"
    assert [row.status for row in executions] == ["completed"]
    assert len(items) == 1
    assert items[0].status == "error"
    assert items[0].research_need_id == "research_5"
    assert items[0].source_type == "case_knowledge"
    assert items[0].excerpt == "research need exceeded the execution deadline"
    assert items[0].provenance["reason"] == "need_deadline_exceeded"
    assert items[0].provenance["error_type"] == "TimeoutError"
    assert items[0].provenance["timeout_seconds"] == 0.05
    assert "need_failed" not in {event.event_type for event in events}
    completed = [event for event in events if event.event_type == "need_completed"]
    assert len(completed) == 1
    assert completed[0].payload["research_need_id"] == "research_5"


@pytest.mark.asyncio
async def test_need_deadline_completes_one_need_and_keeps_the_other(db, monkeypatch):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="deadline-mix")
    monkeypatch.setattr(settings, "research_need_timeout_seconds", 0.25)
    found = RecordingSource("case_knowledge")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(
            needs=[
                _need("slow", "case_knowledge"),
                _need("fast", "case_knowledge"),
            ]
        ),
        router=MixedTimeoutRouter("slow", found),  # type: ignore[arg-type]
        concurrency=2,
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    executions = await list_need_executions(session, attempt.id)
    items = await list_evidence_items(session, evidence_set.id)
    by_need = {row.research_need_id: row.status for row in executions}
    timeout_items = [item for item in items if item.research_need_id == "slow"]
    found_items = [item for item in items if item.research_need_id == "fast"]
    assert result.status == "ready"
    assert reloaded.status == "ready"
    assert evidence_set.status == "frozen"
    assert by_need == {"slow": "completed", "fast": "completed"}
    assert len(timeout_items) == 1
    assert timeout_items[0].status == "error"
    assert timeout_items[0].provenance["reason"] == "need_deadline_exceeded"
    assert found_items
    assert {item.status for item in found_items} == {"found"}
    assessment = await get_research_assessment(session, attempt.id)
    assert assessment is not None
    assert assessment.result == "insufficient"
    by_assessment = {
        row["research_need_id"]: row["sufficient"] for row in assessment.need_assessments
    }
    assert by_assessment["slow"] is False
    assert by_assessment["fast"] is True
    draft = await ProgrammaticResearchAssessor().assess(
        ResearchPlan(needs=[_need("slow", "case_knowledge"), _need("fast", "case_knowledge")]),
        [assessable_from_item(item) for item in items],
    )
    assert draft.result == "insufficient"
    assert {row.research_need_id: row.sufficient for row in draft.need_assessments} == {
        "slow": False,
        "fast": True,
    }


@pytest.mark.asyncio
async def test_timeout_after_completed_need_does_not_write_evidence(db):
    session, factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="late-timeout")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
    )
    executions = await list_need_executions(session, attempt.id)
    items_before = await list_evidence_items(session, result.evidence_set_id)
    assert [row.status for row in executions] == ["completed"]
    assert [item.status for item in items_before] == ["found"]
    await _complete_timed_out_need(
        factory,
        asyncio.Lock(),
        execution_id=executions[0].id,
        need=_need("research_1", "case_knowledge"),
        evidence_set_id=result.evidence_set_id,
        attempt_id=attempt.id,
    )
    items_after = await list_evidence_items(session, result.evidence_set_id)
    executions_after = await list_need_executions(session, attempt.id)
    assert [item.id for item in items_after] == [item.id for item in items_before]
    assert [row.status for row in executions_after] == ["completed"]
    assert all(item.provenance.get("reason") != "need_deadline_exceeded" for item in items_after)
