"""Initial canonical matching and graph reuse release the caller connection."""

import asyncio

import pytest
from sqlalchemy import text

from app.services.research.execution import execute_attempt_research
from app.services.research.planner import ResearchObjective
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from tests.test_research_connection_release import single_connection as single_connection
from tests.test_research_execution import RecordingSource, _created_attempt, _router
from tests.test_research_graph_v2_reuse import Embeddings, seed_fact


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_full_startup_releases_single_connection_before_remote_work(
    single_connection, research_overgraph, monkeypatch, outcome
):
    engine, factory = single_connection
    checked = []

    async def probe(stage):
        assert engine.pool.checkedout() == 0, stage
        async with factory() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        checked.append(stage)

    class RemoteMatcher:
        embedding_metadata = None

        async def index(self, _candidates):
            await probe("canonical_index")

        async def match(self, **_kwargs):
            await probe("canonical_match")
            return None

    class RemoteEmbeddings(Embeddings):
        async def embed(self, texts):
            await probe("graph_embedding")
            if outcome == "error":
                raise RuntimeError("Remote embedding failed")
            if outcome == "cancel":
                raise asyncio.CancelledError
            return await super().embed(texts)

    monkeypatch.setattr("app.services.research.composition.research_embeddings", RemoteEmbeddings)
    async with factory() as session:
        _customer, _run, attempt = await _created_attempt(session)
        await seed_fact(session, scope="shared")
        await session.commit()
        source = RecordingSource("swedish_preparatory_works")
        request = dict(
            attempt_id=attempt.id,
            research_objective=ResearchObjective(objective="36 § avtalslagen senare lagändringar"),
            router=_router(source)[0],
            question_graph=SqlQuestionEvidenceGraph(matcher=RemoteMatcher()),
            session_factory=factory,
        )
        if outcome == "success":
            result = await execute_attempt_research(session, **request)
            assert result.status == "ready"
            assert source.calls == 0
        else:
            error = RuntimeError if outcome == "error" else asyncio.CancelledError
            with pytest.raises(error):
                await execute_attempt_research(session, **request)
    assert {"canonical_index", "canonical_match", "graph_embedding"} <= set(checked)
    assert engine.pool.checkedout() == 0
