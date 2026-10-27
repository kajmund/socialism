"""Research answer publication through the owner.

The answer fact, question/answer entities (with their identifier aliases), the
episode provenance and dependency edges must land in one atomic owner mutation,
match the direct writer's semantics, and fail closed when the owner rejects it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.answers import ANSWER_PREDICATE, QUESTION_TYPE, find_question
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import DEPENDS_ON, ENTITY, FACT, OBJECT, SUBJECT, SUPPORTS
from app.services.overgraph.owner import OwnerClient, OwnerProtocolError, OvergraphOwner
from app.services.overgraph.owner_facts import answer_fact_key, publish_answer_via_owner
from app.services.overgraph.publish import AnswerPublish, publish_answer_fact
from app.services.overgraph.write import upsert_entity, write_fact
from tests.overgraph_graph_snapshot import graph_snapshot

DIMENSION = 4


def _published(*, dependency_ids=()) -> AnswerPublish:
    return AnswerPublish(
        question_id="question-1",
        question_text="Vad gäller uppsägningstiden?",
        scope=customer_scope(1),
        identity="answer-identity-1",
        evidence_set_id="evidence-set-1",
        attributes={"knowledge_module": "dd", "answer_status": "sufficient"},
        basis=[{"title": "Svar", "excerpt": "Nio månader"}],
        assessment={"sufficient": True},
        dependency_ids=tuple(dependency_ids),
    )


def _seed_dependency(catalog):
    scope = customer_scope(1)
    source = upsert_entity(catalog, NodeInput(
        node_type="legal.source", name="Avtalslagen", scope=scope,
    ))
    target = upsert_entity(catalog, NodeInput(
        node_type="legal.issue", name="Uppsägningstid", scope=scope,
    ))
    fact = write_fact(catalog, FactInput(
        source_id=source.key,
        target_id=target.key,
        scope=scope,
        predicate="legal.rule",
        fact_text="Nio månaders uppsägningstid gäller.",
        sources=(SourceRef("episode", "dependency-episode"),),
        occurrence_key="dependency",
    ))
    return fact.key


@pytest.fixture
def owner_paths():
    root = Path(tempfile.mkdtemp(prefix="ogo-answer-"))
    return root, root / "owner.sock"


async def test_answer_publish_commits_entities_fact_and_provenance_in_one_mutation(
    owner_paths,
):
    root, socket_path = owner_paths
    owner = OvergraphOwner(root / "owner", dimension=DIMENSION, socket_path=socket_path)
    await owner.start()
    client = OwnerClient(socket_path, catalog_id=owner.catalog_id)
    try:
        dependency_key = await _seed_dependency_via_owner(client)
        before = (await client.health())["metrics"]
        published = _published(dependency_ids=(dependency_key, "missing-dependency"))
        fact_id = await publish_answer_via_owner(client, published)
        after = (await client.health())["metrics"]
        assert after["applied"] - before["applied"] == 1

        catalog = owner.catalog
        assert fact_id == answer_fact_key(published)
        question = find_question(catalog, "question-1", 1)
        assert question is not None
        assert question.props["node_type"] == QUESTION_TYPE
        fact = catalog.get_by_key(FACT, fact_id)
        assert fact is not None
        assert fact.props["predicate"] == ANSWER_PREDICATE
        answer = catalog.get_by_key(ENTITY, fact.props["target_key"])
        assert answer is not None
        assert '"evidence_set_id": "evidence-set-1"' in answer.props["attributes_json"]
        assert catalog.get_by_key(ENTITY, "episode:evidence-set-1") is not None
        assert _edge(catalog, fact, question, SUBJECT)
        assert _edge(catalog, fact, answer, OBJECT)
        assert _edge(catalog, catalog.get_by_key(ENTITY, "episode:evidence-set-1"), fact, SUPPORTS)
        dependency = catalog.get_by_key(FACT, dependency_key)
        assert dependency is not None
        assert _edge(catalog, question, dependency, DEPENDS_ON)
    finally:
        await owner.close()


async def _seed_dependency_via_owner(client: OwnerClient) -> str:
    from app.services.overgraph.owner_facts import write_fact_via_owner

    scope = customer_scope(1)
    source = NodeInput(node_type="legal.source", name="Avtalslagen", scope=scope)
    target = NodeInput(node_type="legal.issue", name="Uppsägningstid", scope=scope)
    result = await write_fact_via_owner(
        client,
        FactInput(
            source_id=_entity_key(source),
            target_id=_entity_key(target),
            scope=scope,
            predicate="legal.rule",
            fact_text="Nio månaders uppsägningstid gäller.",
            sources=(SourceRef("episode", "dependency-episode"),),
            occurrence_key="dependency",
        ),
        entities=(source, target),
    )
    return str(result["key"])


def _entity_key(proposed: NodeInput) -> str:
    from app.services.overgraph.write import entity_key

    return entity_key(proposed)


def _edge(catalog, source, target, label) -> bool:
    assert source is not None and target is not None
    assert source.engine_id is not None and target.engine_id is not None
    return catalog.get_edge_by_triple(source.engine_id, target.engine_id, label) is not None


async def test_answer_publish_matches_direct_writer(owner_paths):
    root, socket_path = owner_paths
    direct = open_catalog(root / "direct", kind="knowledge", dimension=DIMENSION)
    dependency_key = _seed_dependency(direct)
    owner = OvergraphOwner(root / "owner", dimension=DIMENSION, socket_path=socket_path)
    await owner.start()
    client = OwnerClient(socket_path, catalog_id=owner.catalog_id)
    try:
        owner_dependency_key = await _seed_dependency_via_owner(client)
        assert owner_dependency_key == dependency_key
        published = _published(dependency_ids=(dependency_key,))
        direct_id = publish_answer_fact(
            direct, _with_fact_id(published, answer_fact_key(published)),
        )
        owner_id = await publish_answer_via_owner(client, published)
        assert owner_id == answer_fact_key(published)
        assert direct_id == owner_id
        assert graph_snapshot(owner.catalog) == graph_snapshot(direct)
    finally:
        await owner.close()
        direct.close()


def _with_fact_id(published: AnswerPublish, fact_id: str) -> AnswerPublish:
    return AnswerPublish(
        question_id=published.question_id,
        question_text=published.question_text,
        scope=published.scope,
        identity=published.identity,
        evidence_set_id=published.evidence_set_id,
        attributes=published.attributes,
        basis=published.basis,
        assessment=published.assessment,
        dependency_ids=published.dependency_ids,
        fact_id=fact_id,
    )


class RejectingClient(OwnerClient):
    def __init__(self, socket_path: Path, *, catalog_id: str, error: str) -> None:
        super().__init__(socket_path, catalog_id=catalog_id)
        self.error = error

    async def mutate(self, mutation_id, patch, *, kind="patch"):
        return {"ok": False, "error": self.error, "mutation_id": mutation_id}


@pytest.mark.parametrize("error", ["queue_full", "idempotency_conflict"])
async def test_answer_publish_fails_closed_on_owner_rejection(owner_paths, error):
    root, socket_path = owner_paths
    owner = OvergraphOwner(root / "owner", dimension=DIMENSION, socket_path=socket_path)
    await owner.start()
    client = RejectingClient(socket_path, catalog_id=owner.catalog_id, error=error)
    try:
        with pytest.raises(OwnerProtocolError):
            await publish_answer_via_owner(client, _published())
        assert owner.catalog.count_nodes_by_labels([FACT]) == 0
        assert owner.catalog.count_nodes_by_labels([ENTITY]) == 0
    finally:
        await owner.close()
