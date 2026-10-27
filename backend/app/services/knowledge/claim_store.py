"""Idempotent persist for classified domain claims."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.claims import (
    KnowledgeClaim,
    KnowledgeClaimError,
    assert_claim_grounding_scope,
    knowledge_claim_id,
)
from app.services.knowledge.events import CLAIM_ADDED, record_graph_event, utc_now
from app.services.overgraph.labels import CLAIM, scope_label
from app.services.overgraph.owner_legal import (
    claim_record as owner_claim_record,
    find_claim_key as owner_find_claim_key,
    is_superseded as owner_is_superseded,
    persist_claim as owner_persist_claim,
    attach_supports as owner_attach_supports,
)
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.knowledge.graph_claim_mirror import attach_claim_supports
from app.services.knowledge.persistence_class import DOMAIN_KNOWLEDGE, classify_persistence


@dataclass(frozen=True)
class PersistedClaim:
    """Outcome of a claim write. The graph node is authoritative."""

    id: str
    identity_key: str


async def persist_knowledge_claims(
    session: AsyncSession,
    claims: Sequence[KnowledgeClaim],
) -> list[PersistedClaim]:
    return [await persist_knowledge_claim(session, claim) for claim in claims]


async def persist_knowledge_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> PersistedClaim:
    stored, _reused = await persist_domain_claim(session, claim)
    return stored


async def persist_domain_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> tuple[PersistedClaim, bool]:
    if not claim.supporting_text_unit_ids:
        raise KnowledgeClaimError(f"claim {claim.id} has no SUPPORTED_BY TextUnits")
    decision = classify_persistence(
        value=claim.value,
        declared_class=claim.persistence_class,
        declared_kind=claim.observation_kind,
    )
    if decision.persistence_class != DOMAIN_KNOWLEDGE:
        raise KnowledgeClaimError(
            f"claim rejected as {decision.persistence_class}: {decision.reason}"
        )
    identity = knowledge_claim_id(
        scope_key=claim.scope.scope_key,
        predicate=claim.predicate,
        value=claim.value,
    )
    if claim.id != identity:
        raise KnowledgeClaimError("claim id does not match stable identity")
    await assert_claim_grounding_scope(session, claim)
    client = get_owner_runtime().require_client()
    existing = await owner_claim_record(
        client, scope_key=claim.scope.scope_key, identity=identity,
    )
    if existing is not None:
        key = identity
        reused = True
    else:
        key = await owner_find_claim_key(
            client, scope_key=claim.scope.scope_key,
            identity_value=claim.value, predicate=claim.predicate,
        ) or identity
        reused = key != identity
    if await owner_is_superseded(client, key):
        raise KnowledgeClaimError(f"claim {key} is superseded")
    await owner_persist_claim(
        client, scope=claim.scope, predicate=claim.predicate,
        value=claim.value, unit_ids=tuple(claim.supporting_text_unit_ids), key=key,
    )
    await owner_attach_supports(
        client, claim_key=key, unit_ids=tuple(claim.supporting_text_unit_ids),
    )
    if not reused:
        await record_graph_event(
            session,
            scope=claim.scope,
            event_type=CLAIM_ADDED,
            node_kind="claim",
            node_id=key,
            related_id=claim.supporting_text_unit_ids[0],
            payload={"predicate": claim.predicate},
            created_at=utc_now(),
        )
    return PersistedClaim(id=key, identity_key=identity), reused


def _graph_key_by_identity(catalog, claim: KnowledgeClaim) -> str | None:
    """Find a graph claim materialised under a legacy key with the same identity."""
    nodes, _ = catalog.query_nodes(
        label_filter={
            "labels": [CLAIM, scope_label(claim.scope.scope_key)],
            "mode": "all",
        },
        limit=100_000,
    )
    for node in nodes:
        props = node.props
        if props.get("predicate") != claim.predicate:
            continue
        if props.get("scope_key") != claim.scope.scope_key:
            continue
        try:
            value = json.loads(str(props.get("value_json") or ""))
        except (TypeError, ValueError):
            continue
        if value == claim.value:
            return node.key
    return None


async def attach_supporting_text_units(
    session: AsyncSession,
    claim_id: str,
    unit_ids: Sequence[str],
) -> None:
    """Attach supporting TextUnits in the graph (idempotent)."""
    client = get_owner_runtime().client
    if client is not None:
        await owner_attach_supports(client, claim_key=claim_id, unit_ids=tuple(unit_ids))
        return
    await asyncio.to_thread(attach_claim_supports, claim_id, tuple(unit_ids))


