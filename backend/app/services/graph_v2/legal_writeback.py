"""Legal adapter: structured claims become source-to-attribute fact edges."""

import json
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.graph_v2.jev_judge import JevFactJudge
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.relationships import KnowledgeRelationship
from app.services.prompt_store import require_active_prompts


async def write_legal_facts(
    session: AsyncSession, *, claims: Sequence[KnowledgeClaim],
    entities: Sequence[KnowledgeEntity],
    embedder: EmbeddingProvider, judge: JevFactJudge | None = None,
    relationships: Sequence[KnowledgeRelationship] = (),
    module: str = "dd",
) -> list[str]:
    if not claims:
        return []
    source = next(entity for entity in entities if entity.entity_type == "legal.source")
    if source.customer_id is None:
        raise ValueError("legal graph projection requires a customer scope")
    scope = source.scope
    subject = await resolve_node(session, NodeInput(
        node_type=source.entity_type, name=source.name, scope=scope,
        identifier_namespace="legal.canonical_uri", identifier=source.key,
        attributes=source.extra,
    ))
    if judge is None:
        prompts = await require_active_prompts(
            session, customer_id=source.customer_id, module=module, language="sv",
        )
        key = ("rattsunderlag.graph_fact_resolution" if module == "rattsunderlag"
               else "research.graph_fact_resolution")
        judge = JevFactJudge(prompts[key])
    entity_by_id = {entity.id: entity for entity in entities}
    grounded_relations = [edge for edge in relationships if
                          edge.from_kind == "entity" and edge.to_kind == "entity"]
    texts = [_fact_text(source.name, claim) for claim in claims]
    texts.extend(_relation_text(edge, entity_by_id) for edge in grounded_relations)
    vectors = await embedder.embed(texts)
    ids: list[str] = []
    for claim, text, vector in zip(claims, texts[:len(claims)], vectors[:len(claims)], strict=True):
        slot = await resolve_node(session, NodeInput(
            node_type="core.attribute", name=claim.predicate, scope=scope,
            identifier_namespace="legal.attribute",
            identifier=f"{source.key}:{claim.predicate}",
        ))
        row, _decision = await resolve_fact(session, FactInput(
            source_id=subject.id, target_id=slot.id, scope=scope,
            predicate=claim.predicate, fact_text=text,
            sources=tuple(SourceRef("text_unit", ref) for ref in claim.supporting_text_unit_ids),
            embedding=tuple(vector), embedding_model=embedder.model,
        ), judge=judge)
        ids.append(row.id)
    for edge, text, vector in zip(
        grounded_relations, texts[len(claims):], vectors[len(claims):], strict=True,
    ):
        left, right = entity_by_id[edge.from_id], entity_by_id[edge.to_id]
        left_node = await _entity_node(session, left)
        right_node = await _entity_node(session, right)
        row, _decision = await resolve_fact(session, FactInput(
            source_id=left_node.id, target_id=right_node.id, scope=scope,
            predicate=edge.relation, fact_text=text,
            sources=tuple(SourceRef("text_unit", ref)
                          for claim in claims for ref in claim.supporting_text_unit_ids),
            embedding=tuple(vector), embedding_model=embedder.model,
        ), judge=judge)
        ids.append(row.id)
    return ids


async def _entity_node(session: AsyncSession, entity: KnowledgeEntity):
    namespace = "legal.canonical_uri" if entity.entity_type == "legal.source" else entity.entity_type
    return await resolve_node(session, NodeInput(
        node_type=entity.entity_type, name=entity.name, scope=entity.scope,
        identifier_namespace=namespace, identifier=entity.key, attributes=entity.extra,
    ))


def _relation_text(
    edge: KnowledgeRelationship, entities: dict[str, KnowledgeEntity],
) -> str:
    verb = {
        "legal.cites": "citerar",
        "legal.applies": "tillämpar",
        "legal.decided_by": "avgjordes av",
    }[edge.relation]
    return f"{entities[edge.from_id].name} {verb} {entities[edge.to_id].name}"


def _fact_text(source_name: str, claim: KnowledgeClaim) -> str:
    value = claim.value.get("value", claim.value)
    detail = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return f"{source_name}: {detail}"
