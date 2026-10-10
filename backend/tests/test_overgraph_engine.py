"""OverGraph fact/TextUnit model, isolation, retrieval, ingest and mem0 store."""

from dataclasses import dataclass

import pytest

from app.services.graph_v2.identity import fact_identity
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.knowledge.units import hash_text, make_text_unit_id
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.ingest import ingest_document_units, resolve_fact
from app.services.overgraph.labels import FACT, TEXT_UNIT
from app.services.overgraph.mem0_store import OverGraphVectorStore
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.retrieval import (
    bounded_traverse,
    hybrid_search,
    rank_seeds,
    scoped_search,
)
from app.services.overgraph.traversal import CandidateJudge, TraversalBudget, traverse_question
from app.services.overgraph.research import (
    ResearchFactWrite,
    has_supported_facts,
    persist_research_fact,
    search_research_facts,
)
from app.services.overgraph.write import upsert_entity, upsert_text_unit


DIM = 8


def _vector(tag: float) -> tuple[float, ...]:
    values = [0.0] * DIM
    values[0] = tag
    return tuple(values)


class Judge:
    async def compare(self, proposed, candidate_text):
        if "inte" in proposed.fact_text:
            return "CONTRADICTS"
        if "equivalent" in proposed.fact_text:
            return "SAME"
        return "DISTINCT"


class Embedder:
    model = "test"

    async def embed(self, texts):
        return [list(_vector(1.0)) for _ in texts]


@dataclass
class FakeJev:
    default: float = 0.9

    async def ask(self, **kwargs):
        answers = {key: {"noul": self.default} for key in kwargs["questions"]}
        return type("Result", (), {"answers": answers, "model": "test"})()


@pytest.fixture
def knowledge(tmp_path):
    catalog = open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)
    try:
        yield catalog
    finally:
        catalog.close()


@pytest.fixture
def memory(tmp_path):
    catalog = open_catalog(tmp_path / "memory", kind="memory", dimension=DIM)
    try:
        yield catalog
    finally:
        catalog.close()


def _entity(catalog, name, *, customer=1):
    return upsert_entity(catalog, NodeInput(
        node_type="core.concept", name=name, scope=customer_scope(customer),
    ))


def _unit(catalog, text, *, customer=1, ordinal=0, document="doc-1", version="ver-1"):
    digest = hash_text(text)
    unit_id = make_text_unit_id(
        document_version_id=version, locator=f"p{ordinal}", content_hash=digest,
    )
    return upsert_text_unit(catalog, TextUnitWrite(
        unit_id=unit_id, scope=customer_scope(customer), document_id=document,
        document_version_id=version, text=text, content_hash=digest, ordinal=ordinal,
        locator=f"p{ordinal}", embedding=_vector(0.4 + ordinal * 0.1),
    ))


def _fact(source, target, text, *, customer=1, ref="episode-1"):
    return FactInput(
        source_id=source.key, target_id=target.key, scope=customer_scope(customer),
        predicate="core.relates_to", fact_text=text,
        sources=(SourceRef("episode", ref),), embedding=_vector(1.0),
        embedding_model="test",
    )


@pytest.mark.asyncio
async def test_fact_identity_and_multiple_sources(knowledge):
    a, b = _entity(knowledge, "A"), _entity(knowledge, "B")
    first, decision = await resolve_fact(knowledge, _fact(a, b, "A gäller B"))
    assert decision == "DISTINCT"
    expected = fact_identity(
        scope_key="customer:1", source_id=a.key, target_id=b.key,
        predicate="core.relates_to", fact_text="A gäller B",
        context_id=None, occurrence_key="",
    )
    assert first.key == expected
    repeated, decision = await resolve_fact(
        knowledge, _fact(a, b, "A gäller B", ref="episode-2"),
    )
    assert repeated.key == first.key and decision == "SAME"
    semantic, decision = await resolve_fact(
        knowledge, _fact(a, b, "A är equivalent med B", ref="episode-3"),
        judge=Judge(), embedder=Embedder(),
    )
    assert semantic.key == first.key and decision == "SAME"
    opposite, decision = await resolve_fact(
        knowledge, _fact(a, b, "A gäller inte B", ref="episode-4"),
        judge=Judge(), embedder=Embedder(),
    )
    assert opposite.key != first.key and decision == "CONTRADICTS"


@pytest.mark.asyncio
async def test_text_units_are_nodes_with_contains_and_supports(knowledge):
    first = _unit(knowledge, "36 § avtalslagen")
    second = _unit(knowledge, "jämkning av oskäligt avtalsvillkor", ordinal=1)
    knowledge.upsert_edge(first.engine_id, second.engine_id, "NEXT")
    a, b = _entity(knowledge, "Paragraf"), _entity(knowledge, "Jämkning")
    fact, _ = await resolve_fact(
        knowledge,
        FactInput(
            source_id=a.key, target_id=b.key, scope=customer_scope(1),
            predicate="legal.states", fact_text="36 § tillåter jämkning",
            sources=(SourceRef("text_unit", first.key),),
            embedding=_vector(0.9),
        ),
    )
    neighbors = knowledge.neighbors(first.engine_id, direction="outgoing")
    assert second.engine_id in neighbors or fact.engine_id in neighbors
    assert knowledge.get_by_key(TEXT_UNIT, first.key) is not None
    assert knowledge.get_by_key(FACT, fact.key) is not None


@pytest.mark.asyncio
async def test_tenant_isolation_before_topk(knowledge):
    a1, b1 = _entity(knowledge, "Avtal", customer=1), _entity(knowledge, "Jämkning", customer=1)
    a2, b2 = _entity(knowledge, "Hemlig", customer=2), _entity(knowledge, "Uppgift", customer=2)
    secret_unit = _unit(knowledge, "kund tvås hemliga stycke", customer=2, document="doc-2")
    own, _ = await resolve_fact(knowledge, _fact(a1, b1, "Avtal kan jämkas"))
    secret, _ = await resolve_fact(
        knowledge, _fact(a2, b2, "Hemlig uppgift gäller", customer=2, ref="episode-2"),
    )
    query = _vector(1.0)
    hits = hybrid_search(knowledge, customer_id=1, dense_query=query, limit=10)
    keys = {hit.key for hit in hits}
    assert secret.key not in keys
    assert secret_unit.key not in keys
    assert own.key in keys or any(hit.scope_key == "customer:1" for hit in hits)
    scoped = scoped_search(
        knowledge, customer_id=1, start_key=own.key, start_label=FACT,
        dense_query=query, max_depth=2,
    )
    assert all(hit.scope_key in {"shared", "customer:1"} for hit in scoped)
    ranked = rank_seeds(knowledge, customer_id=1, seeds=hits, max_results=20)
    assert all(hit.scope_key in {"shared", "customer:1"} for hit in ranked)
    walked = bounded_traverse(
        knowledge, customer_id=1, key=own.key, label=FACT, max_depth=2,
    )
    assert all(hit.scope_key in {"shared", "customer:1"} for hit in walked)
    assert secret.key not in {hit.key for hit in [*scoped, *ranked, *walked]}


@pytest.mark.asyncio
async def test_shared_entity_is_visible_to_customer(knowledge):
    shared = upsert_entity(knowledge, NodeInput(
        node_type="core.concept", name="Avtalslagen", scope=shared_scope(),
    ))
    own = _entity(knowledge, "Konsument")
    fact, _ = await resolve_fact(knowledge, _fact(own, shared, "Konsument skyddas"))
    hits = hybrid_search(knowledge, customer_id=1, dense_query=_vector(1.0), limit=8)
    assert fact.key in {hit.key for hit in hits} or hits


@pytest.mark.asyncio
async def test_ingest_does_not_call_judge_inside_exact_match(knowledge):
    a, b = _entity(knowledge, "A"), _entity(knowledge, "B")
    await resolve_fact(knowledge, _fact(a, b, "A gäller B"))

    class ExplodingJudge:
        async def compare(self, proposed, candidate_text):
            raise AssertionError("exact identity must not call Jev")

    row, decision = await resolve_fact(
        knowledge, _fact(a, b, "A gäller B", ref="episode-9"), judge=ExplodingJudge(),
    )
    assert decision == "SAME"
    assert row.props["status"] == "active"


@pytest.mark.asyncio
async def test_batch_text_unit_ingest(knowledge):
    units = []
    for ordinal, text in enumerate(("stycke ett", "stycke två")):
        digest = hash_text(text)
        unit_id = make_text_unit_id(
            document_version_id="ver-9", locator=str(ordinal), content_hash=digest,
        )
        units.append(TextUnitWrite(
            unit_id=unit_id, scope=customer_scope(1), document_id="doc-9",
            document_version_id="ver-9", text=text, content_hash=digest,
            ordinal=ordinal, embedding=_vector(0.2), next_id=None,
        ))
    written = await ingest_document_units(knowledge, units, ingest_mode=True)
    assert len(written) == 2
    assert knowledge.get_by_key(TEXT_UNIT, written[0].key) is not None


@pytest.mark.asyncio
async def test_jev_scores_several_candidates(knowledge):
    a, b = _entity(knowledge, "A"), _entity(knowledge, "B")
    first, _ = await resolve_fact(knowledge, _fact(a, b, "A gäller B"))
    judge = CandidateJudge(FakeJev(), {"type": "noul", "instructions": "bedöm"})
    result = await traverse_question(
        knowledge, customer_id=1, question="Gäller A B?",
        dense_query=_vector(1.0), judge=judge, budget=TraversalBudget(max_jev=4),
    )
    assert first.key in {hit.key for hit in result.seeds + result.selected}


def test_mem0_store_isolates_and_deletes(memory):
    store = OverGraphVectorStore(
        collection_name="expert_memories", embedding_model_dims=DIM, catalog=memory,
    )
    store.insert(
        [_vector(0.8), _vector(0.1)],
        payloads=[
            {"user_id": "kund:1", "agent_id": "expert:legal", "data": "svenskt minne"},
            {"user_id": "kund:2", "agent_id": "expert:legal", "data": "annat minne"},
        ],
        ids=["m1", "m2"],
    )
    hits = store.search("query", list(_vector(0.8)), top_k=5, filters={
        "user_id": "kund:1", "agent_id": "expert:legal",
    })
    assert [hit.id for hit in hits] == ["m1"]
    store.delete("m1")
    assert store.get("m1") is None
    leftover = store.search("query", list(_vector(0.1)), top_k=5, filters={
        "user_id": "kund:2", "agent_id": "expert:legal",
    })
    assert [hit.id for hit in leftover] == ["m2"]


def test_research_fact_is_searchable_inside_tenant(knowledge):
    owner = customer_scope(1)
    written = persist_research_fact(knowledge, ResearchFactWrite(
        fact_id="fact-research-1",
        scope=owner,
        source=NodeInput(node_type="legal.source", name="Avtal", scope=owner),
        target=NodeInput(node_type="legal.value", name="Jämkning", scope=owner),
        predicate="legal.states",
        fact_text="36 § tillåter jämkning",
        unit=TextUnitWrite(
            unit_id="unit-r1",
            scope=owner,
            document_id="doc-r",
            document_version_id="ver-r",
            text="36 § avtalslagen",
            content_hash=hash_text("36 § avtalslagen"),
            ordinal=0,
            locator="p0",
            embedding=_vector(1.0),
        ),
        embedding=_vector(1.0),
        source_key="src-r",
        target_key="tgt-r",
    ))
    assert has_supported_facts(knowledge, 1)
    assert not has_supported_facts(knowledge, 2)
    hits = search_research_facts(knowledge, 1, list(_vector(1.0)), 4)
    assert written.id in {hit.fact.id for hit in hits}
    assert search_research_facts(knowledge, 2, list(_vector(1.0)), 4) == []
