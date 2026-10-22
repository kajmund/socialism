"""A failed research attempt must keep a safe reason for diagnosis."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.services.execution import get_attempt
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentError,
    ResearchAssessmentDraft,
)
from app.services.research.execution import ResearchExecutionError, execute_attempt_research
from app.services.research.models import ResearchPlan
from app.services.research.progress import list_research_progress_events
from tests.test_research_execution import _created_attempt, _need, _router, RecordingSource


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


class FailingAssessment:
    async def assess(
        self, plan: ResearchPlan, evidence: Sequence[AssessableEvidence]
    ) -> ResearchAssessmentDraft:
        raise ResearchAssessmentError(
            "Evidence sufficiency model context limit exceeded (context_length_exceeded)"
        )


@pytest.mark.asyncio
async def test_failed_research_records_safe_underlying_reason(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="failure-reason")
    found = RecordingSource("case_knowledge", excerpt="skattesats 32%")
    router, _sources = _router(found)

    with pytest.raises(ResearchExecutionError) as raised:
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=router,
            assessor=FailingAssessment(),
        )

    cause = raised.value.__cause__
    assert isinstance(cause, ResearchExecutionError)
    assert "ResearchAssessmentError" in str(cause)
    failed = await get_attempt(session, attempt.id)
    assert failed.status == "failed"
    events = await list_research_progress_events(session, attempt.id)
    failed_events = [event for event in events if event.event_type == "research_failed"]
    assert failed_events
    assert failed_events[-1].payload["reason"] == (
        "ResearchAssessmentError:context_length_exceeded"
    )
