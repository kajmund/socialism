"""Shadow control must overlap the real review and clean up cancelled work."""

import asyncio

import pytest

from app.services.research.completeness import ResearchCompletenessDraft
from app.services.research.fast_controller import ResearchFastController
from app.services.research.fast_gate import GatedResearchAssessor, GatedResearchCompletenessReviewer
from app.services.research.planner import ResearchObjective
from tests.test_research_fast_controller import (
    RecordingAssessor,
    RecordingCompleteness,
    ScriptedJev,
    _evidence,
    _llm_draft,
    _plan,
    _sufficient_nouls,
    jev_settings,  # noqa: F401 -- shared fixture
)

pytestmark = pytest.mark.usefixtures("jev_settings")


@pytest.mark.parametrize("gate", ["assessment", "completeness"])
async def test_shadow_starts_authoritative_review_before_jev_finishes(gate):
    started = asyncio.Event()

    class WaitingJev(ScriptedJev):
        async def ask(self, **kwargs):
            await asyncio.wait_for(started.wait(), timeout=1)
            return await super().ask(**kwargs)

    class Assessor(RecordingAssessor):
        async def assess(self, plan, evidence):
            started.set()
            return await super().assess(plan, evidence)

    class Reviewer(RecordingCompleteness):
        async def review(self, **kwargs):
            started.set()
            return await super().review(**kwargs)

    client = WaitingJev(_sufficient_nouls())
    controller = ResearchFastController(client)
    if gate == "assessment":
        inner = Assessor(_llm_draft(result="insufficient"))
        result = await GatedResearchAssessor(inner, controller).assess(_plan(), [_evidence()])
        assert result.result == "insufficient"
    else:
        inner = Reviewer(ResearchCompletenessDraft(result="incomplete", rationale="llm"))
        result = await GatedResearchCompletenessReviewer(inner, controller).review(
            objective=ResearchObjective(objective="Research question"),
            plan=_plan(),
            runtime_needs=[],
            assessment=None,
            assessments=[],
            evidence=[_evidence()],
        )
        assert result.result == "incomplete"
    assert inner.calls == 1
    assert len(client.states) == 1


async def test_failed_authoritative_review_cancels_shadow_request():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class WaitingJev:
        async def ask(self, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    class FailingAssessor:
        async def assess(self, plan, evidence):
            await started.wait()
            raise ValueError("authoritative review failed")

    gated = GatedResearchAssessor(FailingAssessor(), ResearchFastController(WaitingJev()))
    with pytest.raises(ValueError, match="authoritative review failed"):
        await asyncio.wait_for(gated.assess(_plan(), [_evidence()]), timeout=1)
    assert cancelled.is_set()


async def test_cancelled_shadow_gate_awaits_cleanup_of_both_calls():
    starts = [asyncio.Event(), asyncio.Event()]
    stops = [asyncio.Event(), asyncio.Event()]

    async def block(index):
        starts[index].set()
        try:
            await asyncio.Event().wait()
        finally:
            stops[index].set()

    class WaitingJev:
        async def ask(self, **kwargs):
            return await block(0)

    class WaitingAssessor:
        async def assess(self, plan, evidence):
            return await block(1)

    gated = GatedResearchAssessor(WaitingAssessor(), ResearchFastController(WaitingJev()))
    task = asyncio.create_task(gated.assess(_plan(), [_evidence()]))
    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in starts)), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(event.is_set() for event in stops)
