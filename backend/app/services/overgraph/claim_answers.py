"""Claim ANSWERED_BY question links.

The SQL ``knowledge_claim_answers`` row is the legacy mirror; the graph holds a
``KnowledgeQuestion`` node per logical question and an ``ANSWERED_BY`` edge from the claim.
That keeps reuse queries ("which claims already answer this question?") graph-native.
"""

from __future__ import annotations

import json

from dataclasses import dataclass


from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import (
    ANSWERED_BY,
    CLAIM,
    KNOWLEDGE_QUESTION,
    scope_label,
    visible_scope_keys,
)
from app.services.overgraph.model import GraphRecord


@dataclass(frozen=True)
class ClaimAnswerSource:
    """Optional provenance of the answer link (source type, question id, relation)."""

    source_type: str | None = None
    knowledge_question_id: str | None = None
    relation: str = ANSWERED_BY
    created_at_ms: int = 0


QUESTION_IDENTITY = "knowledge.question"


def question_node_key(scope: KnowledgeTenantScope, question_key: str) -> str:
    return scope_node_key(scope.scope_key, question_key)


def upsert_question_node(
    catalog: Catalog, *, scope: KnowledgeTenantScope, question_key: str,
) -> GraphRecord:
    key = question_node_key(scope, question_key)
    catalog.upsert_node(
        [KNOWLEDGE_QUESTION, scope_label(scope.scope_key)],
        key,
        props={"scope_key": scope.scope_key, "question_key": question_key},
    )
    node = catalog.get_by_key(KNOWLEDGE_QUESTION, key)
    if node is None:
        raise RuntimeError(f"question {question_key} was not written")
    return node


def link_claim_answer(
    catalog: Catalog,
    *,
    claim_key: str,
    scope: KnowledgeTenantScope,
    question_key: str,
    research_need_id: str,
    source: "ClaimAnswerSource | None" = None,
) -> None:
    claim = catalog.get_by_key(CLAIM, claim_key)
    if claim is None or claim.engine_id is None:
        raise RuntimeError(f"cannot link answer to missing claim {claim_key}")
    question = upsert_question_node(catalog, scope=scope, question_key=question_key)
    catalog.upsert_edge(
        claim.engine_id,
        question.engine_id,
        ANSWERED_BY,
        props={
            "research_need_id": research_need_id,
            "source_type": (source.source_type if source else "") or "",
            "knowledge_question_id": (source.knowledge_question_id if source else "") or "",
            "relation": (source.relation if source else ANSWERED_BY),
            "question_key": question_key,
            "created_at_ms": source.created_at_ms if source else 0,
        },
    )


def answered_claim_ids(
    catalog: Catalog, *, research_need_id: str, claim_ids: tuple[str, ...],
) -> list[str]:
    """Claims already linked to this research need (idempotent answer writes)."""
    found: list[str] = []
    for claim_key in claim_ids:
        claim = catalog.get_by_key(CLAIM, claim_key)
        if claim is None or claim.engine_id is None:
            continue
        for engine_id in catalog.neighbors(
            claim.engine_id, direction="outgoing", edge_label_filter=[ANSWERED_BY],
        ):
            edge = catalog.get_edge_by_triple(claim.engine_id, engine_id, ANSWERED_BY)
            if edge is None:
                continue
            if str(edge.props.get("research_need_id") or "") != research_need_id:
                continue
            found.append(claim_key)
            break
    return sorted(found)


def claim_answer_edges(
    catalog: Catalog,
    *,
    customer_id: int,
    question_key: str,
) -> list[tuple[GraphRecord, dict[str, object]]]:
    """Claim nodes plus their ANSWERED_BY edge properties for a question."""
    visible = set(visible_scope_keys(customer_id))
    found: dict[str, tuple[GraphRecord, dict[str, object]]] = {}
    for scope in visible:
        node = catalog.get_by_key(KNOWLEDGE_QUESTION, scope_node_key(scope, question_key))
        if node is None or node.engine_id is None:
            continue
        for engine_id in catalog.neighbors(
            node.engine_id, direction="incoming", edge_label_filter=[ANSWERED_BY],
        ):
            claim = catalog.get(engine_id)
            if claim is None or claim.engine_id is None:
                continue
            claim_scope = str(claim.props.get("scope_key") or "")
            if claim_scope not in visible:
                continue
            if str(claim.props.get("status") or "active") != "active":
                continue
            edge = catalog.get_edge_by_triple(claim.engine_id, node.engine_id, ANSWERED_BY)
            if edge is None:
                continue
            found[str(claim.key)] = (claim, dict(edge.props))
    return [found[key] for key in sorted(found)]


def claim_answers_for_question(
    catalog: Catalog,
    *,
    customer_id: int,
    question_key: str,
    scope_key: str | None = None,
) -> list[GraphRecord]:
    """Active claims that answer a question for the reader's visible scopes."""
    visible = set(visible_scope_keys(customer_id))
    claims: dict[str, GraphRecord] = {}
    for scope in visible:
        node = catalog.get_by_key(KNOWLEDGE_QUESTION, scope_node_key(scope, question_key))
        if node is None or node.engine_id is None:
            continue
        for engine_id in catalog.neighbors(
            node.engine_id, direction="incoming", edge_label_filter=[ANSWERED_BY],
        ):
            claim = catalog.get(engine_id)
            if claim is None:
                continue
            claim_scope = str(claim.props.get("scope_key") or "")
            if claim_scope not in visible or scope_key and claim_scope != scope_key:
                continue
            if str(claim.props.get("status") or "active") != "active":
                continue
            claims[str(claim.key)] = claim
    return [claims[key] for key in sorted(claims)]


def scope_node_key(scope_key: str, question_key: str) -> str:
    from app.services.graph_v2.identity import namespaced, normalized, stable_id

    return stable_id(scope_key, namespaced(QUESTION_IDENTITY), normalized(question_key))


def questions_answered_by_claim(
    catalog: Catalog, *, claim_key: str,
) -> list[tuple[str, str]]:
    """Canonical question id and text for every question this claim answers."""
    claim = catalog.get_by_key(CLAIM, claim_key)
    if claim is None or claim.engine_id is None:
        return []
    found: dict[str, str] = {}
    for node_id in catalog.neighbors(
        claim.engine_id, direction="outgoing", edge_label_filter=[ANSWERED_BY],
    ):
        node = catalog.get(node_id)
        if node is None:
            continue
        attributes = json.loads(str(node.props.get("attributes_json") or "{}"))
        question_id = str(attributes.get("canonical_question_id") or "")
        if question_id:
            found[question_id] = str(node.props.get("name") or "")
    return [(key, found[key]) for key in sorted(found)]
