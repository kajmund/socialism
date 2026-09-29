"""Resolve nodes before facts. Semantic decisions can never bypass structural guards."""

import math
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact, GraphFactRelation, GraphFactSource, GraphIdentifier, GraphNode
from app.database.models import TextUnitRecord
from app.services.graph_v2.identity import fact_identity, namespaced, normalized, stable_id
from app.services.graph_v2.types import FactInput, FactJudge, NodeInput, NodeJudge, SourceRef, TextEmbedder
from app.services.knowledge.scope import KnowledgeTenantScope


def _can_reference(owner: KnowledgeTenantScope, target: GraphNode) -> bool:
    return target.scope_key == owner.scope_key or (
        owner.customer_id is not None and target.scope_key == "shared"
    )


async def resolve_node(
    session: AsyncSession, proposed: NodeInput, *, judge: NodeJudge | None = None,
) -> GraphNode:
    namespaced(proposed.node_type)
    name = normalized(proposed.name)
    scope = proposed.scope.scope_key
    if proposed.identifier_namespace is not None:
        namespace = namespaced(proposed.identifier_namespace)
        identifier = normalized(proposed.identifier or "")
        alias = await _identifier(session, scope, namespace, identifier)
        if alias is not None:
            row = await session.get(GraphNode, alias.node_id)
            if row is None or row.node_type != proposed.node_type:
                raise ValueError("strong identifier conflicts with node type")
            return row
        key = f"{namespace}:{identifier}"
    else:
        key = f"weak:{proposed.context_key}:{name}"
        match = await _resolve_weak_node(
            session, proposed, name=name, key=key, judge=judge,
        )
        if match is not None:
            return match
    node_id = stable_id(scope, proposed.node_type, key)
    row = GraphNode(
        id=node_id, scope_key=scope, customer_id=proposed.scope.customer_id,
        node_type=proposed.node_type, identity_key=key, name=proposed.name.strip(),
        normalized_name=name, attributes=dict(proposed.attributes),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        row = await session.scalar(select(GraphNode).where(
            GraphNode.scope_key == scope, GraphNode.node_type == proposed.node_type,
            GraphNode.identity_key == key,
        ))
        if row is None:
            raise
    if proposed.identifier_namespace is not None:
        row = await _attach_identifier(
            session, row, scope=scope, namespace=namespace, identifier=identifier,
        )
    return row


async def _resolve_weak_node(
    session: AsyncSession, proposed: NodeInput, *, name: str, key: str,
    judge: NodeJudge | None,
) -> GraphNode | None:
    candidates = list((await session.scalars(select(GraphNode).where(
        GraphNode.scope_key == proposed.scope.scope_key,
        GraphNode.node_type == proposed.node_type,
    ).order_by(GraphNode.id).limit(100))).all())
    candidates = [candidate for candidate in candidates
                  if candidate.identity_key.startswith(f"weak:{proposed.context_key}:")]
    for candidate in candidates:
        if candidate.identity_key == key:
            return candidate
    if judge is None:
        return None
    proposed_tokens = set(name.split())

    def local_score(candidate: GraphNode) -> float:
        candidate_tokens = set(candidate.normalized_name.split())
        overlap = len(proposed_tokens & candidate_tokens) / max(
            1, len(proposed_tokens | candidate_tokens),
        )
        return max(overlap, SequenceMatcher(None, name, candidate.normalized_name).ratio())

    ranked = sorted(candidates, key=local_score, reverse=True)
    # A lone same-context candidate is worth a semantic check; larger sets need
    # lexical evidence first to keep model calls bounded and genuinely ambiguous.
    shortlist = ranked[:1] if len(ranked) == 1 else [
        candidate for candidate in ranked[:5] if local_score(candidate) >= 0.35
    ]
    for candidate in shortlist:
        if await judge.same_node(proposed, candidate.name):
            return candidate
    return None


async def _identifier(
    session: AsyncSession, scope: str, namespace: str, identifier: str,
) -> GraphIdentifier | None:
    return await session.scalar(select(GraphIdentifier).where(
        GraphIdentifier.scope_key == scope,
        GraphIdentifier.namespace == namespace,
        GraphIdentifier.identifier == identifier,
    ))


async def _attach_identifier(
    session: AsyncSession, row: GraphNode, *, scope: str, namespace: str, identifier: str,
) -> GraphNode:
    try:
        async with session.begin_nested():
            session.add(GraphIdentifier(
                id=stable_id(scope, namespace, identifier), scope_key=scope,
                namespace=namespace, identifier=identifier, node_id=row.id,
            ))
            await session.flush()
    except IntegrityError:
        winner = await _identifier(session, scope, namespace, identifier)
        if winner is None:
            raise
        resolved = await session.get(GraphNode, winner.node_id)
        if resolved is None or resolved.node_type != row.node_type:
            raise ValueError("strong identifier conflicts with node type")
        return resolved
    return row


async def resolve_fact(
    session: AsyncSession, proposed: FactInput, *, judge: FactJudge | None = None,
    embedder: TextEmbedder | None = None,
) -> tuple[GraphFact, str]:
    exact = await resolve_exact_fact(session, proposed)
    if exact is not None:
        return exact, "SAME"
    namespaced(proposed.predicate)
    normalized(proposed.fact_text)
    identity = fact_identity(
        scope_key=proposed.scope.scope_key, source_id=proposed.source_id,
        target_id=proposed.target_id, predicate=proposed.predicate,
        context_id=proposed.context_id, occurrence_key=proposed.occurrence_key,
        fact_text=proposed.fact_text,
    )
    candidates = list((await session.scalars(_candidate_query(proposed))).all())
    vector = list(proposed.embedding) if proposed.embedding is not None else None
    if vector is None and embedder is not None:
        vector = (await embedder.embed([proposed.fact_text]))[0]
    if candidates and judge is None:
        raise ValueError("fact judge required for non-exact candidates")
    contradiction = None
    for candidate in _rank_candidates(candidates, vector)[:5]:
        decision = await judge.compare(proposed, candidate.fact_text)  # type: ignore[union-attr]
        if decision == "SAME":
            await _attach_sources(session, candidate.id, proposed.sources)
            return candidate, decision
        if decision == "CONTRADICTS":
            # A contradiction is recorded, never an implicit invalidation.
            contradiction = contradiction or candidate
            continue
        if decision != "DISTINCT":
            raise ValueError(f"invalid fact judge decision: {decision}")
    row = GraphFact(
        id=identity, identity_key=identity, scope_key=proposed.scope.scope_key,
        customer_id=proposed.scope.customer_id, source_id=proposed.source_id,
        target_id=proposed.target_id, context_id=proposed.context_id,
        predicate=proposed.predicate, fact_text=proposed.fact_text.strip(),
        normalized_text=normalized(proposed.fact_text), embedding=vector,
        embedding_model=embedder.model if embedder is not None else proposed.embedding_model,
        occurrence_key=proposed.occurrence_key, valid_at=proposed.valid_at,
        status="active", attributes=dict(proposed.attributes),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        row = await session.get(GraphFact, identity)
        if row is None:
            raise
    await _attach_sources(session, row.id, proposed.sources)
    if contradiction is not None and contradiction.id != row.id:
        await _relate_contradiction(session, row.id, contradiction.id)
    return row, "CONTRADICTS" if contradiction is not None else "DISTINCT"


async def resolve_exact_fact(session: AsyncSession, proposed: FactInput) -> GraphFact | None:
    """Validate and attach provenance to an exact edge before any embedding call."""
    namespaced(proposed.predicate)
    normalized(proposed.fact_text)
    if not proposed.sources:
        raise ValueError("fact requires at least one episode or TextUnit")
    await _validate_endpoints(session, proposed)
    await _validate_sources(session, proposed.scope, proposed.sources)
    identity = fact_identity(
        scope_key=proposed.scope.scope_key, source_id=proposed.source_id,
        target_id=proposed.target_id, predicate=proposed.predicate,
        context_id=proposed.context_id, occurrence_key=proposed.occurrence_key,
        fact_text=proposed.fact_text,
    )
    exact = await session.get(GraphFact, identity)
    if exact is not None:
        await _attach_sources(session, exact.id, proposed.sources)
    return exact


def _candidate_query(proposed: FactInput):
    return select(GraphFact).where(
        GraphFact.scope_key == proposed.scope.scope_key,
        GraphFact.source_id == proposed.source_id,
        GraphFact.target_id == proposed.target_id,
        GraphFact.predicate == proposed.predicate,
        GraphFact.context_id == proposed.context_id,
        GraphFact.occurrence_key == proposed.occurrence_key,
        GraphFact.status == "active",
    ).limit(100)


def _rank_candidates(candidates: list[GraphFact], vector: list[float] | None) -> list[GraphFact]:
    if vector is None:
        return candidates
    def similarity(row: GraphFact) -> float:
        other = row.embedding
        if not other or len(other) != len(vector):
            return -1.0
        length = math.sqrt(sum(x * x for x in vector) * sum(x * x for x in other))
        return sum(x * y for x, y in zip(vector, other, strict=True)) / length if length else -1.0
    return sorted(candidates, key=similarity, reverse=True)


async def _validate_endpoints(session: AsyncSession, proposed: FactInput) -> None:
    for node_id in (proposed.source_id, proposed.target_id, proposed.context_id):
        if node_id is None:
            continue
        row = await session.get(GraphNode, node_id)
        if row is None or not _can_reference(proposed.scope, row):
            raise ValueError("fact endpoint is missing or outside tenant scope")


async def _validate_sources(
    session: AsyncSession, scope: KnowledgeTenantScope, sources: tuple[SourceRef, ...],
) -> None:
    for source in sources:
        if not source.ref.strip():
            raise ValueError("empty provenance reference")
        if source.kind == "text_unit":
            unit = await session.get(TextUnitRecord, source.ref)
            if unit is None or unit.scope_key not in (scope.scope_key, "shared"):
                raise ValueError("TextUnit provenance is missing or outside tenant scope")
        elif source.kind != "episode":
            raise ValueError("unsupported provenance kind")


async def _attach_sources(
    session: AsyncSession, fact_id: str, sources: tuple[SourceRef, ...],
) -> None:
    for source in set(sources):
        try:
            async with session.begin_nested():
                session.add(GraphFactSource(
                    fact_id=fact_id, source_kind=source.kind, source_ref=source.ref,
                ))
                await session.flush()
        except IntegrityError:
            exists = await session.scalar(select(GraphFactSource.id).where(
                GraphFactSource.fact_id == fact_id,
                GraphFactSource.source_kind == source.kind,
                GraphFactSource.source_ref == source.ref,
            ))
            if exists is None:
                raise


async def _relate_contradiction(session: AsyncSession, first: str, second: str) -> None:
    left, right = sorted((first, second))
    try:
        async with session.begin_nested():
            session.add(GraphFactRelation(
                from_fact_id=left, predicate="core.contradicts", to_fact_id=right,
            ))
            await session.flush()
    except IntegrityError:
        exists = await session.scalar(select(GraphFactRelation.id).where(
            GraphFactRelation.from_fact_id == left,
            GraphFactRelation.to_fact_id == right,
            GraphFactRelation.predicate == "core.contradicts",
        ))
        if exists is None:
            raise
