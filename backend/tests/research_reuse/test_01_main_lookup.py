from unittest.mock import AsyncMock

import pytest

from app.services.research.execution import execute_attempt_research
from app.services.research.graph_reuse import lookup_graph_evidence
from app.services.research.planner import FakeResearchPlanner, ResearchNeedDraft
from tests.research_reuse.helpers import MAIN, attempt, context, need, objective
from tests.research_reuse.probes import lookup
from tests.test_research_graph_v2_reuse import Embeddings
from tests.test_research_question_evidence import RecordingSource, _router

pytestmark = pytest.mark.research_reuse


@pytest.mark.parametrize("question", [MAIN, need().question], ids=["main", "child"])
async def test_graph_lookup_preserves_grounding_and_scope(graph_basis, question):
    items = await lookup(graph_basis, need(question=question), context(), Embeddings())
    assert items and all(item.provider == "graph_v2" for item in items)
    assert items[0].metadata["supporting_text_unit_ids"] == ["unit-customer-1"]
    assert (
        await lookup(graph_basis, need(question=question), context(customer_id=2), Embeddings())
        == []
    )


async def test_unavailable_embedding_is_an_error_not_empty_knowledge(graph_basis):
    embedding = Embeddings()
    embedding.embed = AsyncMock(side_effect=RuntimeError("embedding unavailable"))
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await lookup(graph_basis, need(), context(), embedding)


async def test_invalidated_facts_do_not_answer_main_question(graph_basis):
    from app.database.graph_v2 import GraphFact

    async with graph_basis.begin() as session:
        fact = await session.get(GraphFact, "fact-customer-1")
        fact.status = "invalidated"
    assert await lookup(graph_basis, need(question=MAIN), context(), Embeddings()) == []


async def test_main_question_is_looked_up_before_decomposition(graph_basis, monkeypatch):
    trace = []
    real_lookup = lookup_graph_evidence

    async def observed_lookup(session, **kwargs):
        trace.append("lookup:" + kwargs["need"].question)
        return await real_lookup(session, **kwargs)

    planner = FakeResearchPlanner(
        [
            ResearchNeedDraft(
                question=need().question,
                why_needed="Lucka",
                source_types=need().source_types,
            )
        ]
    )
    real_plan = planner.plan_research

    async def observed_plan(**kwargs):
        trace.append("decompose")
        return await real_plan(**kwargs)

    monkeypatch.setattr("app.services.research.graph_lookup.lookup_graph_evidence", observed_lookup)
    monkeypatch.setattr(planner, "plan_research", observed_plan)
    router, _ = _router(RecordingSource("swedish_preparatory_works"))
    async with graph_basis() as session:
        row = await attempt(session)
        await session.commit()
        await execute_attempt_research(
            session,
            attempt_id=row.id,
            research_objective=objective(),
            research_planner=planner,
            router=router,
            session_factory=graph_basis,
        )
    assert trace[0] == "lookup:" + MAIN, trace


async def test_main_reuse_is_assessed_with_objective_context(graph_basis):
    from types import SimpleNamespace
    from app.services.research.planner import ResearchObjective
    from tests.research_reuse.helpers import reviewed_answer

    adapter = SimpleNamespace(assess=AsyncMock(side_effect=reviewed_answer))
    reviewer = SimpleNamespace(review=AsyncMock(side_effect=AssertionError("Already assessed")))
    planner = FakeResearchPlanner([])
    source = RecordingSource("swedish_preparatory_works")
    async with graph_basis() as session:
        row = await attempt(session)
        row.research_objective_snapshot = {"objective": MAIN, "context": {"contract": "commercial lease"}}
        await session.commit()
        result = await execute_attempt_research(
            session,
            attempt_id=row.id,
            research_objective=ResearchObjective(MAIN, context={"contract": "commercial lease"}),
            research_planner=planner,
            assessor=adapter,
            completeness_reviewer=reviewer,
            router=_router(source)[0],
            session_factory=graph_basis,
        )
    assert result.status == "ready"
    assert adapter.assess.await_count == 1
    assert '"contract": "commercial lease"' in adapter.assess.call_args.args[0].needs[0].why_needed
    assert source.calls == 0 and planner.calls == []
    reviewer.review.assert_not_awaited()
