"""Owner-backed clause matching: anchors, verification validity and query vector."""

from __future__ import annotations

from app.services.clause_ssr import owner_select
from app.services.clause_ssr.labels import VERIFICATION
from app.services.clause_ssr.match import (
    _category_scores,
    _decide_labels,
    _rank_hits,
    _same_embedding,
)
from app.services.clause_ssr.types import (
    LABEL_ANSWERS,
    Anchor,
    EmbeddingSpec,
    MatchResult,
)
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_text_units import get_unit_vector


def _str(props: dict, name: str) -> str:
    return str(props.get(name) or "")


async def _members(
    client: OwnerClient,
    *,
    scope: KnowledgeTenantScope,
    embedding: EmbeddingSpec,
    set_id: str | None,
) -> list[Anchor]:
    sets = await owner_select.list_anchor_sets(
        client, customer_id=scope.customer_id, active_only=True,
    )
    if set_id is not None:
        sets = [item for item in sets if item.id == set_id]
    allowed: set[str] = set()
    for item in sets:
        if _same_embedding(item.embedding, embedding):
            allowed.update(item.member_ids)
    if not allowed:
        raise ValueError("no active anchor set matches the embedding spec")
    anchors = await owner_select.list_anchors(
        client, customer_id=scope.customer_id, statuses=("draft", "active"),
    )
    members = [
        anchor for anchor in anchors
        if anchor.id in allowed and anchor.vector is not None
        and _same_embedding(anchor.embedding, embedding)
    ]
    verification_ids = [anchor.verification_id for anchor in members if anchor.verification_id]
    response = await client.read([
        {"label": VERIFICATION, "key": key} for key in dict.fromkeys(verification_ids)
    ])
    usable: list[Anchor] = []
    for anchor in members:
        props = response["values"].get(f"{VERIFICATION}:{anchor.verification_id}") or {}
        if (
            _str(props, "status") == "active"
            and _str(props, "answer") in LABEL_ANSWERS
            and _str(props, "polarity") == anchor.polarity
        ):
            usable.append(anchor)
    return usable


async def match_query(
    client: OwnerClient,
    *,
    scope: KnowledgeTenantScope,
    embedding: EmbeddingSpec,
    vector: list[float] | None = None,
    text_unit_id: str | None = None,
    k: int = 8,
    set_id: str | None = None,
) -> MatchResult:
    if text_unit_id is not None:
        query = await get_unit_vector(client, text_unit_id)
        if query is None:
            raise ValueError("text unit has no stored embedding")
        if len(query) != embedding.dimension:
            raise ValueError("text unit embedding dimension does not match")
    else:
        if vector is None:
            raise ValueError("match requires a text_unit_id or a dense_vector")
        if len(vector) != embedding.dimension:
            raise ValueError("query embedding dimension does not match")
        query = list(vector)
    members = await _members(
        client, scope=scope, embedding=embedding, set_id=set_id,
    )
    hits = _rank_hits(query, members)[:k]
    scores = _category_scores(query, members)
    labels, abstained, reason = _decide_labels(scores)
    return MatchResult(
        top_k=tuple(hits), category_scores=tuple(scores), labels=labels,
        abstained=abstained, abstain_reason=reason, embedding=embedding,
    )
