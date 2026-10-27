"""Owner-backed review queue: classification, decisions, units and centroid."""

from __future__ import annotations

from app.services.clause_ssr import owner_classifications, owner_select
from app.services.clause_ssr.keys import review_key
from app.services.clause_ssr.labels import VERIFICATION
from app.services.clause_ssr.queue import _card, _labeled_count, _unit_order
from app.services.clause_ssr.types import (
    ClassificationDefinition,
    QueuePage,
    ReviewSession,
)
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.isolation import can_reference
from app.services.overgraph.labels import TEXT_UNIT, visible_scope_keys
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.owner import OwnerClient

PAGE_LIMIT = 1000


def _unit_record(row: dict) -> GraphRecord:
    return GraphRecord(
        key=str(row["key"]), labels=tuple(row.get("labels") or (TEXT_UNIT,)),
        props=dict(row.get("props") or {}), engine_id=row.get("id"),
        dense_vector=tuple(row.get("dense_vector") or ()) or None,
    )


async def _eligible_units(
    client: OwnerClient,
    *,
    scope: KnowledgeTenantScope,
    document_id: str | None,
    seen_units: set[str],
    seen_hashes: set[str],
) -> list[GraphRecord]:
    eligible: list[GraphRecord] = []
    used_hashes = set(seen_hashes)
    for scope_key in visible_scope_keys(scope.customer_id):
        cursor: int | None = None
        while True:
            page = await client.query_nodes(
                TEXT_UNIT, props={"scope_key": scope_key}, include_vectors=True,
                limit=PAGE_LIMIT, after=cursor,
            )
            for raw in page["nodes"]:
                row = _unit_record(raw)
                if row.key in seen_units:
                    continue
                text = str(row.props.get("text") or "").strip()
                if not text:
                    continue
                if document_id and str(row.props.get("document_id") or "") != document_id:
                    continue
                digest = str(row.props.get("content_hash") or "")
                if digest and digest in used_hashes:
                    continue
                if digest:
                    used_hashes.add(digest)
                eligible.append(row)
            cursor = page.get("next_cursor")
            if cursor is None:
                break
    eligible.sort(key=_unit_order)
    return eligible


async def _decisions(
    client: OwnerClient, *, classification_id: str, reviewer_id: str,
) -> list[dict]:
    cursor: int | None = None
    decisions: list[dict] = []
    key = review_key(classification_id, reviewer_id)
    while True:
        page = await client.query_nodes(
            VERIFICATION, props={"review_key": key}, limit=PAGE_LIMIT, after=cursor,
        )
        decisions.extend(
            row for row in page["nodes"]
            if str((row.get("props") or {}).get("status") or "") == "active"
        )
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    return decisions


async def _positive_centroid(
    client: OwnerClient,
    *,
    scope: KnowledgeTenantScope,
    classification: ClassificationDefinition,
) -> list[float] | None:
    anchors = await owner_select.list_anchors(
        client, customer_id=scope.customer_id,
        classification_id=classification.id, statuses=("draft", "active"),
    )
    vectors = [
        anchor.vector for anchor in anchors
        if anchor.polarity == "positive" and anchor.vector is not None
    ]
    if not vectors:
        return None
    dim = len(vectors[0])
    acc = [0.0] * dim
    for vector in vectors:
        if len(vector) != dim:
            continue
        for index, value in enumerate(vector):
            acc[index] += value
    count = float(len(vectors))
    return [value / count for value in acc]


async def next_queue(
    client: OwnerClient,
    *,
    scope: KnowledgeTenantScope,
    classification_id: str,
    reviewer_id: str,
    document_id: str | None = None,
    limit: int = 5,
    session: ReviewSession | None = None,
) -> QueuePage:
    classification = await owner_classifications.get(client, classification_id)
    if not can_reference(scope, classification.scope_key):
        raise PermissionError("classification is outside the caller tenant")
    if session is None:
        from app.services.clause_ssr.repository import ClauseRepository

        props = await ClauseRepository(client).get_or_create_session(
            scope=scope, reviewer_id=reviewer_id,
            classification_id=classification_id, document_id=document_id,
        )
        session = ReviewSession(
            id=str(props.get("id") or ""), reviewer_id=reviewer_id,
            classification_id=classification_id,
            document_id=str(props.get("document_id") or "") or None,
            last_unit_id=str(props.get("last_unit_id") or "") or None,
            last_verification_id=str(props.get("last_verification_id") or "") or None,
            decided_yes=int(props.get("decided_yes") or 0),
            decided_no=int(props.get("decided_no") or 0),
            skipped=int(props.get("skipped") or 0),
            unsure=int(props.get("unsure") or 0),
            scope_key=scope.scope_key,
        )
    decisions = await _decisions(
        client, classification_id=classification_id, reviewer_id=reviewer_id,
    )
    seen_units = {str(row["props"].get("source_unit_id") or "") for row in decisions}
    seen_hashes = {
        str(row["props"].get("content_hash") or "") for row in decisions
        if row["props"].get("content_hash")
    }
    units = await _eligible_units(
        client, scope=scope, document_id=document_id,
        seen_units=seen_units, seen_hashes=seen_hashes,
    )
    centroid = await _positive_centroid(
        client, scope=scope, classification=classification,
    )
    cards = tuple(_card(unit, classification, centroid) for unit in units[:limit])
    return QueuePage(
        cards=cards, session=session, remaining=len(units),
        total_eligible=len(units) + _labeled_count(session),
    )
