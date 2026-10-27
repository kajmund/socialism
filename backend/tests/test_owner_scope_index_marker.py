"""Owner fact writes must materialise the scope index marker atomically."""

from __future__ import annotations

from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.labels import ENTITY, scope_label
from app.services.overgraph.owner_facts import write_fact_via_owner
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.publish import AnswerPublish
from app.services.overgraph.owner_facts import publish_answer_via_owner
from app.services.overgraph.research import INDEX_PREFIX, graph_has_supported_facts, lookup_candidates


def _unit(scope) -> dict:
    return {
        "labels": ["TextUnit", scope_label(scope.scope_key)],
        "key": "index-unit",
        "props": {
            "scope_key": scope.scope_key, "text": "x", "content_hash": "h",
            "document_id": "doc", "document_version_id": "ver",
        },
    }


def _entity(key: str, scope) -> dict:
    return {
        "labels": [ENTITY, scope_label(scope.scope_key)], "key": key,
        "props": {"scope_key": scope.scope_key, "node_type": "legal.source"},
    }


async def test_text_unit_fact_writes_scope_index_marker_and_is_searchable():
    scope = customer_scope(1)
    client = get_owner_runtime().require_client()
    await client.mutate("index-seed", {"upsert_nodes": [
        _entity("source", scope), _entity("target", scope), _unit(scope),
    ]}, kind="batch")
    vector = [0.0] * 32
    vector[0] = 1.0
    proposed = FactInput(
        source_id="source", target_id="target", scope=scope,
        predicate="legal.rule", fact_text="Nio månader",
        sources=(SourceRef("text_unit", "index-unit"),),
        occurrence_key="index-fact", embedding=tuple(vector),
    )
    result = await write_fact_via_owner(client, proposed, mutation_id="index-fact-write")
    assert result["result"]["ok"] is True
    marker_key = f"{INDEX_PREFIX}{scope.scope_key}"
    from app.services.overgraph.catalogs import require_knowledge

    row = require_knowledge().get_by_key(ENTITY, marker_key)
    assert row is not None
    assert row.props["has_text_unit_facts"] == 1
    assert await graph_has_supported_facts(1) is True
    hits = await lookup_candidates(
        customer_id=1, question_id=None, dense_query=vector, bound=5,
    )
    assert result["key"] in {hit.fact.id for hit in hits}

    # A failed mutation must not leave a marker behind: the marker is only
    # committed together with a successful fact+provenance patch.
    failed_scope = customer_scope(3)
    await client.mutate("index-failed-seed", {"upsert_nodes": [
        _entity("source-3", failed_scope),
        _entity("target-3", failed_scope),
        {**_unit(failed_scope), "key": "index-unit-3"},
    ]}, kind="batch")
    failed = FactInput(
        source_id="source-3", target_id="missing-target-3", scope=failed_scope,
        predicate="legal.rule", fact_text="missing target",
        sources=(SourceRef("text_unit", "index-unit-3"),),
        occurrence_key="index-failed",
    )
    import pytest

    from app.services.graph_v2.errors import PermanentGraphError

    with pytest.raises(PermanentGraphError):
        await write_fact_via_owner(client, failed, mutation_id="index-fact-failed")
    assert require_knowledge().get_by_key(
        ENTITY, f"{INDEX_PREFIX}{failed_scope.scope_key}",
    ) is None


async def test_answer_fact_does_not_create_scope_index_marker():
    published = AnswerPublish(
        question_id="index-answer-question",
        question_text="Fråga?",
        scope=customer_scope(2),
        identity="index-answer-identity",
        evidence_set_id="index-answer-set",
        attributes={"knowledge_module": "dd", "answer_status": "sufficient"},
        basis=[{"title": "Svar"}],
        assessment={"sufficient": True},
        dependency_ids=(),
    )
    client = get_owner_runtime().require_client()
    await publish_answer_via_owner(client, published)
    from app.services.overgraph.catalogs import require_knowledge

    markers, _ = require_knowledge().query_nodes(
        label_filter={"labels": [ENTITY], "mode": "all"}, limit=100,
    )
    assert not any(
        row.key == f"{INDEX_PREFIX}customer:2" for row in markers
    )
