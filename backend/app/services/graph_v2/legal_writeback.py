"""Legal adapter: structured facts link source/context subjects to reusable values."""

import json
from dataclasses import replace
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeClaimAnswer, KnowledgeQuestionRow
from app.services.graph_v2.jev_judge import JevFactJudge, JevNodeJudge
from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.questions import question_node
from app.services.graph_v2.revalidation import attach_question_dependency
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_exact_fact, resolve_fact, resolve_node
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.entities import KnowledgeEntity
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.prompt_store import require_active_prompts


async def write_legal_facts(
    session: AsyncSession,
    *,
    claims: Sequence[KnowledgeClaim],
    entities: Sequence[KnowledgeEntity],
    embedder: EmbeddingProvider,
    judge: JevFactJudge | None = None,
    node_judge: JevNodeJudge | None = None,
    module: str = "dd",
) -> list[str]:
    if not claims:
        return []
    source = _source_entity(entities)
    if source.customer_id is None:
        raise PermanentGraphError("legal graph projection requires a customer scope")
    scope = source.scope
    subject = await resolve_node(
        session,
        NodeInput(
            node_type=source.entity_type,
            name=source.name,
            scope=scope,
            identifier_namespace="legal.canonical_uri",
            identifier=source.key,
            attributes=source.extra,
        ),
    )
    lazy_judges = _LazyJudges(
        session,
        customer_id=source.customer_id,
        module=module,
        fact_judge=judge,
        node_judge=node_judge,
    )
    pending: list[tuple[KnowledgeClaim, FactInput]] = []
    ids_by_claim: dict[str, str] = {}
    for claim in claims:
        text = _fact_text(source.name, claim)
        target = await resolve_node(session, value_node_input(claim, scope), judge=lazy_judges.node)
        proposed = FactInput(
            source_id=subject.id,
            target_id=target.id,
            scope=scope,
            predicate=claim.predicate,
            fact_text=text,
            sources=tuple(SourceRef("text_unit", ref) for ref in claim.supporting_text_unit_ids),
        )
        exact = await resolve_exact_fact(session, proposed)
        if exact is not None:
            ids_by_claim[claim.id] = exact.id
        else:
            pending.append((claim, proposed))

    # Exact edge resolution precedes provider work; all remaining misses are one batch.
    texts = [proposed.fact_text for _, proposed in pending]
    if not texts:
        vectors = []
    elif isinstance(embedder, GraphEmbeddingCacheProvider):
        vectors = await embedder.embed_in_session(session, texts)
    else:
        vectors = await embedder.embed(texts)
    for (claim, proposed), vector in zip(pending, vectors, strict=True):
        row, _decision = await resolve_fact(
            session,
            replace(proposed, embedding=tuple(vector), embedding_model=embedder.model),
            judge=lazy_judges.fact,
        )
        ids_by_claim[claim.id] = row.id

    ids: list[str] = []
    for claim in claims:
        fact_id = ids_by_claim[claim.id]
        question_ids = set(
            (
                await session.scalars(
                    select(KnowledgeClaimAnswer.knowledge_question_id).where(
                        KnowledgeClaimAnswer.claim_id == claim.id,
                        KnowledgeClaimAnswer.knowledge_question_id.is_not(None),
                    )
                )
            ).all()
        )
        for question_id in sorted(question_ids):
            question = await session.get(KnowledgeQuestionRow, question_id)
            if question is None:
                continue
            question_node_row = await question_node(session, question)
            await attach_question_dependency(
                session,
                question_node_id=question_node_row.id,
                fact_id=fact_id,
            )
        ids.append(fact_id)
    return ids


class _LazyJudges:
    def __init__(
        self,
        session,
        *,
        customer_id: int,
        module: str,
        fact_judge: JevFactJudge | None,
        node_judge: JevNodeJudge | None,
    ) -> None:
        self.session = session
        self.customer_id = customer_id
        self.module = module
        self.fact_judge = fact_judge
        self.node_judge = node_judge
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        if self.fact_judge is not None and self.node_judge is not None:
            self._loaded = True
            return
        prompts = await require_active_prompts(
            self.session,
            customer_id=self.customer_id,
            module=self.module,
            language="sv",
        )
        prefix = "rattsunderlag" if self.module == "rattsunderlag" else "research"
        self.fact_judge = self.fact_judge or JevFactJudge(
            prompts[f"{prefix}.graph_fact_resolution"]
        )
        self.node_judge = self.node_judge or JevNodeJudge(
            prompts[f"{prefix}.graph_node_resolution"]
        )
        self._loaded = True

    @property
    def fact(self):
        return _LazyJudgeProxy(self, "fact")

    @property
    def node(self):
        return _LazyJudgeProxy(self, "node")


def _source_entity(entities: Sequence[KnowledgeEntity]) -> KnowledgeEntity:
    source = next((entity for entity in entities if entity.entity_type == "legal.source"), None)
    if source is None:
        raise PermanentGraphError("legal graph projection payload has no source entity")
    return source


class _LazyJudgeProxy:
    def __init__(self, owner: _LazyJudges, kind: str) -> None:
        self.owner = owner
        self.kind = kind

    async def compare(self, proposed: FactInput, candidate_text: str):
        await self.owner._load()
        return await self.owner.fact_judge.compare(proposed, candidate_text)

    async def same_node(self, proposed: NodeInput, candidate_name: str) -> bool:
        await self.owner._load()
        return await self.owner.node_judge.same_node(proposed, candidate_name)


def _fact_text(source_name: str, claim: KnowledgeClaim) -> str:
    value = claim.value.get("value", claim.value)
    detail = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
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
        node_type=f"{claim.predicate}.value",
        name=name,
        scope=scope,
        attributes={"value": value},
    )
