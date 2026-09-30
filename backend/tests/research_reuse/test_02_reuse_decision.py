import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.services.research import ResearchPlan, execute_attempt_research
from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
from tests.research_reuse.helpers import (
    assessor,
    attempt,
    context,
    evidence,
    need,
    pending_contract,
)
from tests.research_reuse.probes import assess, lookup
from tests.test_research_graph_v2_reuse import Embeddings
from tests.test_research_question_evidence import RecordingSource, _router

pytestmark = pytest.mark.research_reuse


@pytest.mark.parametrize("sufficient", [True, False], ids=["answer-reusable", "actual-gap"])
async def test_model_assesses_the_exact_question_and_graph_evidence(reuse_db, sufficient):
    adapter, completer = assessor(sufficient=sufficient)
    builder = AsyncMock(return_value=adapter)
    result = await assess(reuse_db, need(), [evidence()], context(), builder=builder)
    messages = completer.call_args.args[0]
    assert need().question in messages[1]["content"]
    assert evidence().evidence_id in messages[1]["content"]
    assert result.result == ("sufficient" if sufficient else "insufficient")


async def test_stale_evidence_is_not_presented_as_fresh_support(reuse_db):
    adapter = AsyncMock()
    adapter.assess.return_value = ResearchAssessmentDraft(result="insufficient", rationale="stale")
    await assess(
        reuse_db,
        need(),
        [evidence(freshness="stale")],
        context(),
        builder=AsyncMock(return_value=adapter),
    )
    assert adapter.assess.call_args.args[1] == []


async def test_assessor_failure_propagates_without_search_or_substitute(reuse_db):
    adapter = AsyncMock()
    adapter.assess.side_effect = RuntimeError("model unavailable")
    with pytest.raises(RuntimeError, match="model unavailable"):
        await assess(
            reuse_db, need(), [evidence()], context(), builder=AsyncMock(return_value=adapter)
        )


@pending_contract("Punkt 2: providers are currently called before sufficiency is assessed")
async def test_sufficient_graph_answer_skips_external_source_for_child(graph_basis):
    source = RecordingSource("swedish_preparatory_works")
    router, _ = _router(source)

    async def sufficient_answer(_plan, items):
        supporting = [item.evidence_id for item in items if item.provider == "graph_v2"]
        return ResearchAssessmentDraft(
            result="sufficient",
            rationale="Existing answer is sufficient",
            need_assessments=[
                ResearchNeedAssessment(
                    research_need_id="child",
                    sufficient=True,
                    supporting_evidence_ids=supporting,
                )
            ],
            considered_evidence_ids=supporting,
        )

    adapter = SimpleNamespace(assess=AsyncMock(side_effect=sufficient_answer))
    async with graph_basis() as session:
        row = await attempt(session)
        await session.commit()
        result = await execute_attempt_research(
            session,
            attempt_id=row.id,
            research_plan=ResearchPlan(needs=[need()]),
            router=router,
            assessor=adapter,
            session_factory=graph_basis,
        )
    assert result.status == "ready"
    assert adapter.assess.await_count >= 1
    assert source.calls == 0, "An adequate Graph answer must skip external retrieval"


async def test_single_pool_connection_is_available_during_embedding_and_assessment(graph_basis):
    async def other_client():
        async with graph_basis() as other:
            assert await other.scalar(text("SELECT 1")) == 1

    embedding = Embeddings()
    original = embedding.embed

    async def external_embedding(texts):
        await asyncio.wait_for(other_client(), timeout=1)
        return await original(texts)

    embedding.embed = external_embedding
    items = await lookup(graph_basis, need(), context(), embedding)
    adapter = AsyncMock()

    async def external_assessment(_plan, _items):
        await asyncio.wait_for(other_client(), timeout=1)
        return ResearchAssessmentDraft(result="sufficient", rationale="Confirmed")

    adapter.assess.side_effect = external_assessment

    async def builder(session, **_kwargs):
        await session.execute(text("SELECT 1"))
        return adapter

    await assess(graph_basis, need(), items, context(), builder=builder)
