"""Owner-backed legal projection: claims become facts, questions link to them."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace

from app.services.graph_v2.legal_writeback import (
    _fact_text,
    _source_entity,
    value_node_input,
)
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.answers import QUESTION_NS, QUESTION_TYPE
from app.services.overgraph.labels import (
    ANSWERED_BY,
    CLAIM,
    DEPENDS_ON,
    ENTITY,
    FACT,
)
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_facts import write_fact_via_owner
from app.services.overgraph.owner_graph import (
    apply_batch,
    make_edge,
)
from app.services.overgraph.write import entity_key, entity_nodes

QUESTION_READ_LIMIT = 200


async def questions_answered_by_claim(
    client: OwnerClient, claim_key: str,
) -> list[tuple[str, str]]:
    response = await client.read([{"label": CLAIM, "key": claim_key}])
    claim_id = response.get("ids", {}).get(f"{CLAIM}:{claim_key}")
    if claim_id is None:
        return []
    rows = await client.neighbors(claim_id, labels=[ANSWERED_BY], limit=QUESTION_READ_LIMIT)
    if len(rows) >= QUESTION_READ_LIMIT:
        raise RuntimeError(f"claim {claim_key} has too many answered questions")
    found: dict[str, str] = {}
    for row in rows:
        props = dict(row.get("props") or {})
        attributes = json.loads(str(props.get("attributes_json") or "{}"))
        question_id = str(attributes.get("canonical_question_id") or "")
        if question_id:
            found[question_id] = str(props.get("name") or "")
    return [(key, found[key]) for key in sorted(found)]


async def attach_question_dependency(
    client: OwnerClient,
    *,
    question_id: str,
    question_text: str,
    fact_id: str,
    scope: KnowledgeTenantScope,
) -> None:
    proposed = NodeInput(
        node_type=QUESTION_TYPE,
        name=question_text,
        scope=scope,
        identifier_namespace=QUESTION_NS,
        identifier=question_id,
        attributes={"canonical_question_id": question_id},
    )
    key = entity_key(proposed)
    _, nodes = entity_nodes(proposed)
    await apply_batch(
        client, "legal:question", nodes=list(nodes),
        edges=[make_edge((ENTITY, key), (FACT, fact_id), DEPENDS_ON)],
    )


async def write_legal_facts_via_owner(
    client: OwnerClient,
    *,
    claims: Sequence[KnowledgeClaim],
    entities: Sequence[KnowledgeEntity],
    embedder: EmbeddingProvider,
    module: str = "dd",
) -> list[str]:
    """Publish every claim fact and its question dependencies through the Owner."""
    del module
    if not claims:
        return []
    source = _source_entity(entities)
    scope = source.scope
    source_input = NodeInput(
        node_type=source.entity_type,
        name=source.name,
        scope=scope,
        identifier_namespace="legal.canonical_uri",
        identifier=source.key,
        attributes=source.extra,
    )
    texts = [_fact_text(source.name, claim) for claim in claims]
    vectors = await embedder.embed(texts)
    ids: list[str] = []
    for claim, text, vector in zip(claims, texts, vectors, strict=True):
        target_input = value_node_input(claim, scope)
        proposed = FactInput(
            source_id=entity_key(source_input),
            target_id=entity_key(target_input),
            scope=scope,
            predicate=claim.predicate,
            fact_text=text,
            sources=tuple(
                SourceRef("text_unit", ref) for ref in claim.supporting_text_unit_ids
            ),
            embedding=tuple(vector),
            embedding_model=embedder.model,
        )
        result = await write_fact_via_owner(
            client, replace(proposed), entities=(source_input, target_input),
        )
        fact_id = str(result["key"])
        for question_id, question_text in await questions_answered_by_claim(client, claim.id):
            await attach_question_dependency(
                client, question_id=question_id, question_text=question_text,
                fact_id=fact_id, scope=scope,
            )
        ids.append(fact_id)
    return ids
