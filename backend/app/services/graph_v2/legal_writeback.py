"""Legal adapter: structured claims become source-to-attribute fact edges."""

import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeClaimAnswer, KnowledgeQuestionRow
from app.services.graph_v2.jev_judge import JevFactJudge, JevNodeJudge
from app.services.graph_v2.questions import question_node
from app.services.graph_v2.revalidation import attach_question_dependency
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.prompt_store import require_active_prompts


async def write_legal_facts(
    session: AsyncSession, *, claims: Sequence[KnowledgeClaim],
    entities: Sequence[KnowledgeEntity],
    embedder: EmbeddingProvider, judge: JevFactJudge | None = None,
    node_judge: JevNodeJudge | None = None,
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
    if judge is None or node_judge is None:
        prompts = await require_active_prompts(
            session, customer_id=source.customer_id, module=module, language="sv",
        )
        prefix = "rattsunderlag" if module == "rattsunderlag" else "research"
        if judge is None:
            judge = JevFactJudge(prompts[f"{prefix}.graph_fact_resolution"])
        if node_judge is None:
            node_judge = JevNodeJudge(prompts[f"{prefix}.graph_node_resolution"])
    texts = [_fact_text(source.name, claim) for claim in claims]
    vectors = await embedder.embed(texts)
    ids: list[str] = []
    for claim, text, vector in zip(claims, texts, vectors, strict=True):
        target = await resolve_node(session, value_node_input(claim, scope), judge=node_judge)
        row, _decision = await resolve_fact(session, FactInput(
            source_id=subject.id, target_id=target.id, scope=scope,
            predicate=claim.predicate, fact_text=text,
            sources=tuple(SourceRef("text_unit", ref) for ref in claim.supporting_text_unit_ids),
            embedding=tuple(vector), embedding_model=embedder.model,
        ), judge=judge)
        question_ids = set((await session.scalars(select(KnowledgeClaimAnswer.knowledge_question_id).where(
            KnowledgeClaimAnswer.claim_id == claim.id,
            KnowledgeClaimAnswer.knowledge_question_id.is_not(None),
        ))).all())
        for question_id in sorted(question_ids):
            question = await session.get(KnowledgeQuestionRow, question_id)
            if question is None:
                continue
            question_node_row = await question_node(session, question)
            await attach_question_dependency(
                session, question_node_id=question_node_row.id, fact_id=row.id,
            )
        ids.append(row.id)
    return ids


def _fact_text(source_name: str, claim: KnowledgeClaim) -> str:
    value = claim.value.get("value", claim.value)
    detail = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return f"{source_name} — {claim.predicate}: {detail}"


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
        node_type=f"{claim.predicate}.value", name=name, scope=scope,
        attributes={"value": value},
    )
