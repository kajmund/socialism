"""Legal adapter: structured facts link source/context subjects to reusable values."""

import asyncio
import json
from dataclasses import replace
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.scope import KnowledgeTenantScope, require_persist_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.claim_answers import questions_answered_by_claim
from app.services.overgraph.research import attach_question_dependency
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.publish import link_legal_questions, publish_legal_fact
from app.services.overgraph.text_units import load_domain_text_unit
from app.services.overgraph.write import fact_key


async def write_legal_facts(
    session: AsyncSession,
    *,
    claims: Sequence[KnowledgeClaim],
    entities: Sequence[KnowledgeEntity],
    embedder: EmbeddingProvider,
    module: str = "dd",
) -> list[str]:
    if not claims:
        return []
    source = _source_entity(entities)
    if source.customer_id is None:
        raise PermanentGraphError("legal graph projection requires a customer scope")
    scope = source.scope
    pending: list[tuple[KnowledgeClaim, FactInput]] = []
    ids_by_claim: dict[str, str] = {}
    for claim in claims:
        text = _fact_text(source.name, claim)
        proposed = FactInput(
            source_id=source.key,
            target_id=claim.id,
            scope=scope,
            predicate=claim.predicate,
            fact_text=text,
            sources=tuple(SourceRef("text_unit", ref) for ref in claim.supporting_text_unit_ids),
        )
        pending.append((claim, proposed))

    # Exact edge resolution precedes provider work; all remaining misses are one batch.
    texts = [proposed.fact_text for _, proposed in pending]
    if not texts:
        vectors = []
    elif isinstance(embedder, GraphEmbeddingCacheProvider):
        vectors = await embedder.embed_in_session(session, texts)
    else:
        vectors = await embedder.embed(texts)
    catalog = require_knowledge()
    for (claim, proposed), vector in zip(pending, vectors, strict=True):
        # Additive contract: deterministic identity, no semantic merge, no Jev gate.
        stamped = replace(proposed, embedding=tuple(vector), embedding_model=embedder.model)
        ids_by_claim[claim.id] = await asyncio.to_thread(fact_key, stamped, catalog)

    ids: list[str] = []
    for claim in claims:
        fact_id = ids_by_claim[claim.id]
        questions = await asyncio.to_thread(
            questions_answered_by_claim, require_knowledge(), claim_key=claim.id,
        )
        for question_id, question_text in questions:
            await asyncio.to_thread(
                attach_question_dependency,
                require_knowledge(),
                question_id=question_id,
                question_text=question_text,
                fact_id=fact_id,
                scope=require_persist_scope(
                    scope_type=source.scope.scope_type, customer_id=source.scope.customer_id,
                ),
            )
        ids.append(fact_id)
    await _publish_overgraph(
        session, claims=claims, source=source, ids_by_claim=ids_by_claim,
        pending=pending, vectors=vectors,
    )
    return ids




def _source_entity(entities: Sequence[KnowledgeEntity]) -> KnowledgeEntity:
    source = next((entity for entity in entities if entity.entity_type == "legal.source"), None)
    if source is None:
        raise PermanentGraphError("legal graph projection payload has no source entity")
    return source




def _fact_text(source_name: str, claim: KnowledgeClaim) -> str:
    value = claim.value.get("value", claim.value)
    detail = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
    return f"{source_name} — {claim.predicate}: {detail}"


async def _publish_overgraph(session, *, claims, source, ids_by_claim, pending, vectors) -> None:
    catalog = require_knowledge()
    scope = source.scope
    source_input = NodeInput(
        node_type=source.entity_type,
        name=source.name,
        scope=scope,
        identifier_namespace="legal.canonical_uri",
        identifier=source.key,
        attributes=source.extra,
    )
    embedded = {
        proposed.fact_text: vector
        for (_, proposed), vector in zip(pending, vectors, strict=True)
    }
    for claim in claims:
        text = _fact_text(source.name, claim)
        units = []
        for ref in claim.supporting_text_unit_ids:
            unit = await asyncio.to_thread(load_domain_text_unit, catalog, unit_id=ref)
            if unit is None:
                raise PermanentGraphError(f"legal fact missing TextUnit {ref}")
            units.append(TextUnitWrite(
                unit_id=unit.id,
                scope=scope,
                document_id=unit.document_id,
                document_version_id=unit.document_version_id,
                text=unit.text,
                content_hash=unit.content_hash,
                ordinal=unit.ordinal,
                locator=unit.locator,
                page_start=unit.page_start,
                page_end=unit.page_end,
            ))
        vector = embedded.get(text)
        publish_legal_fact(
            catalog,
            FactInput(
                source_id=source.key,
                target_id=claim.id,
                scope=scope,
                predicate=claim.predicate,
                fact_text=text,
                sources=tuple(SourceRef("text_unit", ref) for ref in claim.supporting_text_unit_ids),
                embedding=tuple(vector) if vector is not None else None,
            ),
            fact_id=ids_by_claim[claim.id],
            source=source_input,
            target=value_node_input(claim, scope),
            units=units,
        )
        questions = await asyncio.to_thread(
            questions_answered_by_claim, require_knowledge(), claim_key=claim.id,
        )
        link_legal_questions(
            catalog, fact_id=ids_by_claim[claim.id], scope=scope, questions=questions,
        )


def value_node_input(claim: KnowledgeClaim, scope: KnowledgeTenantScope) -> NodeInput:
    """A typed value is reusable across sources; source identity stays on the fact edge."""
    value = claim.value.get("value", claim.value)
    if claim.predicate == "legal.adjustment_granted" and isinstance(value, bool):
        name = "Adjustment granted" if value else "No adjustment"
    elif isinstance(value, str):
        name = value.replace("_", " ").strip()
    else:
        name = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return NodeInput(
        node_type=f"{claim.predicate}.value",
        name=name,
        scope=scope,
        attributes={"value": value},
    )
