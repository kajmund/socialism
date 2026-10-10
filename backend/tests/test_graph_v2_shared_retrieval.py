"""Shared-only retrieval scopes every candidate source before limits or expansion."""

from types import SimpleNamespace

import pytest

from app.database.graph_v2 import GraphFact
from app.services.graph_v2.retrieval import _semantic_candidates, hybrid_facts, neighbourhood
from tests.conftest import research_test_vector
from tests.test_research_graph_v2_reuse import (
    Embeddings,
    graph_db as graph_db,
    seed_fact,
)


@pytest.mark.parametrize("query", ["36 avtalslagen", "Unrelated lexical query"])
async def test_shared_lexical_and_semantic_top_k_exclude_customer_facts(graph_db, query):
    await seed_fact(graph_db, scope="customer:1")
    await seed_fact(graph_db, scope="customer:2")
    shared = await seed_fact(graph_db, scope="shared")
    hits = await hybrid_facts(graph_db, customer_id=None, query=query,
        embedding=research_test_vector(), embedding_model=Embeddings.model, limit=1)
    assert [hit.fact.id for hit in hits] == [shared.id]


async def test_shared_neighbourhood_never_traverses_private_facts(graph_db):
    private = await seed_fact(graph_db, scope="customer:1")
    shared = await seed_fact(graph_db, scope="shared")
    row = await graph_db.get(GraphFact, private.id)
    row.source_id = shared.source_id
    await graph_db.flush()
    hits = await neighbourhood(graph_db, customer_id=None, seeds=[shared.source_id], max_hops=2)
    assert {hit.fact.id for hit in hits} == {shared.id}


async def test_postgres_semantic_shared_reader_binds_only_shared_scope():
    captured = []
    fact = SimpleNamespace(id="fact-shared")

    class Session:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def scalars(self, statement, params=None):
            captured.append((statement, params))
            rows = [fact.id] if params is not None else [fact]
            return SimpleNamespace(all=lambda: rows)

    result = await _semantic_candidates(Session(), customer_id=None,
        embedding=research_test_vector(), model=Embeddings.model, limit=20)
    assert result == [fact]
    assert captured[0][1]["owned"] == "shared"
    assert "scope_key IN (:owned, 'shared')" in str(captured[0][0])
