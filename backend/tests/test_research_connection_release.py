"""Model work must leave the sole pool connection available to other work."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.services.research import quality_persist
from app.services.research.execution import execute_attempt_research
from app.services.research.models import ResearchPlan
from tests.test_research_assessment import _fixed_draft
from tests.test_research_completeness import (
    SequenceCompletenessReviewer,
    _complete,
    _incomplete,
    _missing,
    _objective,
)
from tests.test_research_execution import RecordingSource, _created_attempt, _need, _router
from tests.test_research_loop import ScriptedPlanner, SequenceAssessor, _follow_up


@pytest.fixture
async def single_connection(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/pool.sqlite",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine, factory
    await engine.dispose()


@pytest.mark.parametrize("path", ["local", "global"])
async def test_model_boundaries_allow_another_db_client(single_connection, monkeypatch, path):
    engine, factory = single_connection
    checked = []

    async def probe(stage):
        assert engine.pool.checkedout() == 0, stage
        # Simulate the worker heartbeat/UI while model work is in progress.
        async with factory() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        checked.append(stage)

    class Assessor(SequenceAssessor):
        async def assess(self, plan, evidence):
            await probe("assessment")
            return await super().assess(plan, evidence)

    class Planner(ScriptedPlanner):
        async def plan_follow_ups(self, **kwargs):
            await probe("follow_up")
            return await super().plan_follow_ups(**kwargs)

    class Reviewer(SequenceCompletenessReviewer):
        async def review(self, **kwargs):
            await probe("completeness")
            return await super().review(**kwargs)

    class Normalizer:
        async def normalize_plan(self, plan):
            await probe("initial_normalization")
            return plan

        async def normalize_follow_up_drafts(self, drafts):
            await probe("follow_up_normalization")
            return drafts

    original_quality = quality_persist.assess_evidence_quality

    async def score(*args, **kwargs):
        await probe("quality")
        return await original_quality(*args, **kwargs)

    monkeypatch.setattr(quality_persist, "assess_evidence_quality", score)
    drafts = [
        _fixed_draft(result=result, need_id="research_1", evidence_ids=[])
        for result in (["insufficient", "sufficient"] if path == "local" else ["sufficient"])
    ]
    reviews = (
        [_incomplete(_missing("Vilka transaktioner skedde 2024?")), _complete()]
        if path == "global" else [_complete()]
    )
    async with factory() as session:
        _, _, attempt = await _created_attempt(session)
        result = await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_objective=_objective(),
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=_router(RecordingSource("case_knowledge"))[0],
            assessor=Assessor(drafts),
            planner=Planner([[_follow_up("Vilken historik finns?", parent=None)]]),
            completeness_reviewer=Reviewer(reviews),
            need_normalizer=Normalizer(),
            session_factory=factory,
        )
        assert result.status == "ready"
    assert {"quality", "assessment", "completeness", "initial_normalization",
            "follow_up_normalization"} <= set(checked)
    if path == "local":
        assert "follow_up" in checked
