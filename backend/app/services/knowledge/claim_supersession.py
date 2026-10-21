"""Supersession of claims that live only in OverGraph.

The SQL row is the legacy mirror; when it is absent (claims written after the cutover) the
claim is closed in the graph with the same semantics: status, validity window, successor.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.events import CLAIM_SUPERSEDED, record_graph_event, utc_now
from app.services.knowledge.scope import require_persist_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import claim_is_superseded, mark_claim_superseded


async def supersede_graph_claim(
    session: AsyncSession,
    claim_id: str,
    error_type,
    *,
    successor,
    at: datetime | None,
    valid_to: datetime | None,
):
    """Close a graph-only claim (the SQL row no longer exists)."""
    catalog = require_knowledge()
    node = catalog.get_by_key("Claim", claim_id)
    if node is None:
        raise error_type(f"claim {claim_id} is missing")
    if claim_is_superseded(catalog, claim_id):
        raise error_type(f"claim {claim_id} is already superseded")
    stamp = at or utc_now()
    successor_id = None
    if successor is not None:
        from app.services.knowledge.claim_store import persist_knowledge_claim

        stored = await persist_knowledge_claim(session, successor)
        successor_id = stored.id
        if successor_id == claim_id:
            raise error_type("a claim cannot supersede itself")
    await asyncio.to_thread(
        mark_claim_superseded,
        catalog,
        claim_id,
        superseded_at=stamp,
        valid_to=valid_to or stamp,
        successor_id=successor_id,
    )
    await record_graph_event(
        session,
        scope=require_persist_scope(customer_id=_scope_customer(node)),
        event_type=CLAIM_SUPERSEDED,
        node_kind="claim",
        node_id=claim_id,
        related_id=successor_id or "",
        payload={"successor_id": successor_id or ""},
        created_at=stamp,
    )
    from app.services.knowledge.claim_store import PersistedClaim

    return PersistedClaim(id=claim_id, identity_key=claim_id)


def _scope_customer(node) -> int | None:
    scope_key = str(node.props.get("scope_key") or "")
    return int(scope_key.split(":", 1)[1]) if scope_key.startswith("customer:") else None
