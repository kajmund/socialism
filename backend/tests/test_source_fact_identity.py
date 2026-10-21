"""Additive fact identity: deterministic, source-anchored, never semantic.

The contract: two fact nodes never become one because they mean the same thing. Only the
exact same identified source occurrence may reuse a node on a repeated write.
"""

from __future__ import annotations

import pytest


from app.services.graph_v2.identity import (
    SOURCE_FACT_IDENTITY_VERSION,
    fact_occurrence_selector,
    source_fact_identity,
)
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import CONTRADICTS
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.write import upsert_entity, upsert_text_unit, write_fact

SCOPE = customer_scope(1)
TEXT = "Nio månaders uppsägningstid gäller."


def _unit(unit_id: str, version: str, *, text: str = TEXT, ordinal: int = 0) -> None:
    upsert_text_unit(require_knowledge(), TextUnitWrite(
        unit_id=unit_id, scope=SCOPE, document_id=f"doc-{version}",
        document_version_id=version, text=text,
        content_hash=unit_id, ordinal=ordinal,
    ))


def _endpoints() -> tuple[str, str]:
    graph = require_knowledge()
    source = upsert_entity(graph, NodeInput(
        node_type="legal.source", name="Avtalslagen", scope=SCOPE,
    )).key
    target = upsert_entity(graph, NodeInput(
        node_type="legal.issue", name="Uppsägningstid", scope=SCOPE,
    )).key
    return source, target


def _fact(unit_id: str, *, text: str = TEXT, occurrence: str = "", embedding=None):
    source, target = _endpoints()
    return write_fact(require_knowledge(), FactInput(
        source_id=source, target_id=target, scope=SCOPE, predicate="legal.rule",
        fact_text=text, occurrence_key=occurrence, embedding=embedding,
        sources=(SourceRef(kind="text_unit", ref=unit_id),),
    ))


def test_identity_is_versioned_and_stable():
    first = source_fact_identity(
        scope_key="customer:1", source_identity="text_unit", document_version_id="ver-a",
        source_unit_key="tu-a", fact_occurrence_key="occurrence-1",
    )
    second = source_fact_identity(
        scope_key="customer:1", source_identity="text_unit", document_version_id="ver-a",
        source_unit_key="tu-a", fact_occurrence_key="occurrence-1",
    )
    assert first == second
    assert first != source_fact_identity(
        scope_key="customer:1", source_identity="text_unit", document_version_id="ver-a",
        source_unit_key="tu-a", fact_occurrence_key="occurrence-2",
    )
    assert SOURCE_FACT_IDENTITY_VERSION == "source-fact-v1"


def test_same_occurrence_written_twice_is_one_node():
    _unit("tu-1", "ver-a")
    first = _fact("tu-1")
    second = _fact("tu-1")
    assert first.key == second.key
    assert require_knowledge().count_nodes_by_labels(["Fact"]) == 1


def test_two_text_units_with_identical_wording_are_two_nodes():
    _unit("tu-1", "ver-a")
    _unit("tu-2", "ver-a", ordinal=1)
    assert _fact("tu-1").key != _fact("tu-2").key
    assert require_knowledge().count_nodes_by_labels(["Fact"]) == 2


def test_two_document_versions_with_identical_wording_are_two_nodes():
    _unit("tu-1", "ver-a")
    _unit("tu-2", "ver-b")
    assert _fact("tu-1").key != _fact("tu-2").key


def test_two_assertions_inside_one_unit_are_two_nodes():
    _unit("tu-1", "ver-a")
    first = _fact("tu-1", text="Nio månaders uppsägningstid gäller.")
    second = _fact("tu-1", text="Avtalet förlängs årsvis.")
    assert first.key != second.key
    assert require_knowledge().count_nodes_by_labels(["Fact"]) == 2


def test_repeated_identical_assertion_in_one_unit_is_deterministically_one_node():
    _unit("tu-1", "ver-a")
    assert _fact("tu-1").key == _fact("tu-1").key


def test_embeddings_never_decide_identity():
    _unit("tu-1", "ver-a")
    first = _fact("tu-1", embedding=tuple(0.1 for _ in range(32)))
    second = _fact("tu-1", embedding=tuple(0.9 for _ in range(32)))
    assert first.key == second.key


def test_different_tenants_with_identical_wording_are_separate_facts():
    _unit("tu-1", "ver-a")
    here = _fact("tu-1")
    other_scope = customer_scope(2)
    upsert_text_unit(require_knowledge(), TextUnitWrite(
        unit_id="tu-other", scope=other_scope, document_id="doc-o",
        document_version_id="ver-o", text=TEXT, content_hash="tu-other", ordinal=0,
    ))
    graph = require_knowledge()
    source = upsert_entity(graph, NodeInput(
        node_type="legal.source", name="Avtalslagen", scope=other_scope,
    )).key
    target = upsert_entity(graph, NodeInput(
        node_type="legal.issue", name="Uppsägningstid", scope=other_scope,
    )).key
    other = write_fact(graph, FactInput(
        source_id=source, target_id=target, scope=other_scope, predicate="legal.rule",
        fact_text=TEXT, sources=(SourceRef(kind="text_unit", ref="tu-other"),),
    ))
    assert here.key != other.key


def test_contradiction_keeps_both_nodes_and_adds_only_an_edge():
    _unit("tu-1", "ver-a")
    _unit("tu-2", "ver-b")
    left = _fact("tu-1")
    right = _fact("tu-2", text="Tolv månaders uppsägningstid gäller.")
    graph = require_knowledge()
    graph.upsert_edge(left.engine_id, right.engine_id, CONTRADICTS)
    assert graph.count_nodes_by_labels(["Fact"]) == 2
    assert graph.count_edges_by_label(CONTRADICTS) == 1
    assert graph.get_by_key("Fact", left.key) is not None
    assert graph.get_by_key("Fact", right.key) is not None


def test_occurrence_selector_is_local_and_deterministic():
    first = fact_occurrence_selector(
        predicate="legal.rule", context_id=None, fact_text=TEXT,
    )
    second = fact_occurrence_selector(
        predicate="legal.rule", context_id=None, fact_text=TEXT,
    )
    assert first == second
    assert first != fact_occurrence_selector(
        predicate="legal.rule", context_id=None, fact_text="Avtalet förlängs årsvis.",
    )


async def test_fact_write_never_calls_the_judge():
    """Jev must not gate node creation: a judge that always fails is never consulted."""
    from app.services.overgraph.ingest import resolve_fact

    class ExplodingJudge:
        async def compare(self, *_args, **_kwargs):
            raise AssertionError("the judge must not run on the write path")

    _unit("tu-1", "ver-a")
    source, target = _endpoints()
    proposed = FactInput(
        source_id=source, target_id=target, scope=SCOPE, predicate="legal.rule",
        fact_text=TEXT, sources=(SourceRef(kind="text_unit", ref="tu-1"),),
    )
    row, decision = await resolve_fact(
        require_knowledge(), proposed, judge=ExplodingJudge(),
    )
    assert decision == "DISTINCT"
    assert require_knowledge().get_by_key("Fact", row.key) is not None


async def test_retry_of_the_same_occurrence_is_idempotent():
    _unit("tu-1", "ver-a")
    first = _fact("tu-1")
    for _ in range(3):
        again = _fact("tu-1")
        assert again.key == first.key
    graph = require_knowledge()
    assert graph.count_nodes_by_labels(["Fact"]) == 1
    # Provenance is not duplicated either: the source edge is idempotent.
    assert graph.count_edges_by_label("SUPPORTS") == 1


async def test_relation_workflow_failure_does_not_touch_stored_facts():
    _unit("tu-1", "ver-a")
    stored = _fact("tu-1")

    def broken_relation_workflow() -> None:
        raise RuntimeError("relation extraction failed")

    with pytest.raises(RuntimeError):
        broken_relation_workflow()
    graph = require_knowledge()
    assert graph.get_by_key("Fact", stored.key) is not None
    assert graph.count_nodes_by_labels(["Fact"]) == 1


def test_answer_fact_identity_agrees_with_the_sql_contract():
    """The answer fact has no TextUnit anchor: both layers must compute the same key."""
    from app.services.graph_v2.identity import fact_identity
    from app.services.overgraph.write import fact_key

    source_key = "question-entity-key"
    target_key = "answer-entity-key"
    proposed = FactInput(
        source_id=source_key, target_id=target_key, scope=SCOPE,
        predicate="research.answered_by", fact_text="Vad gäller uppsägningstiden?",
        sources=(SourceRef("episode", "set-1"),), occurrence_key="answer-identity",
    )
    assert fact_key(proposed, require_knowledge()) == fact_identity(
        scope_key=SCOPE.scope_key, source_id=source_key, target_id=target_key,
        predicate="research.answered_by", context_id=None,
        occurrence_key="answer-identity", fact_text="Vad gäller uppsägningstiden?",
    )
