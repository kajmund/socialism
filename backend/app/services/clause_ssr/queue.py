"""Deterministic verification queue over existing TextUnits."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import TEXT_UNIT
from app.services.overgraph.model import GraphRecord
from app.services.ssr.similarity import cosine_similarity

from app.services.overgraph.isolation import can_reference

from app.services.clause_ssr.anchors import list_anchors
from app.services.clause_ssr.classifications import get_classification
from app.services.clause_ssr.graph import list_visible, prop_int, prop_str
from app.services.clause_ssr.sessions import get_or_create_session
from app.services.clause_ssr.types import (
    ClassificationDefinition,
    QueueCard,
    QueuePage,
    ReviewSession,
)
from app.services.clause_ssr.verifications import list_reviewer_decisions


def next_queue(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    classification_id: str,
    reviewer_id: str,
    document_id: str | None = None,
    limit: int = 5,
    session: ReviewSession | None = None,
) -> QueuePage:
    classification = get_classification(catalog, classification_id)
    if not can_reference(scope, classification.scope_key):
        raise PermissionError("classification is outside the caller tenant")
    if session is None:
        session = get_or_create_session(
            catalog,
            scope=scope,
            reviewer_id=reviewer_id,
            classification_id=classification_id,
            document_id=document_id,
        )
    decided = list_reviewer_decisions(
        catalog, classification_id=classification_id, reviewer_id=reviewer_id,
    )
    seen_units = {item.source_unit_id for item in decided}
    seen_hashes = {item.content_hash for item in decided if item.content_hash}
    units = _eligible_units(
        catalog,
        scope=scope,
        document_id=document_id,
        seen_units=seen_units,
        seen_hashes=seen_hashes,
    )
    centroid = _positive_centroid(catalog, scope, classification)
    cards = tuple(
        _card(unit, classification, centroid) for unit in units[:limit]
    )
    return QueuePage(
        cards=cards,
        session=session,
        remaining=len(units),
        total_eligible=len(units) + _labeled_count(session),
    )


def _eligible_units(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    document_id: str | None,
    seen_units: set[str],
    seen_hashes: set[str],
) -> list[GraphRecord]:
    eligible: list[GraphRecord] = []
    used_hashes = set(seen_hashes)
    for row in list_visible(catalog, TEXT_UNIT, scope.customer_id):
        if row.key in seen_units:
            continue
        text = prop_str(row, "text").strip()
        if not text:
            continue
        if document_id and prop_str(row, "document_id") != document_id:
            continue
        digest = prop_str(row, "content_hash")
        if digest and digest in used_hashes:
            continue
        if digest:
            used_hashes.add(digest)
        eligible.append(row)
    eligible.sort(key=_unit_order)
    return eligible


def _unit_order(row: GraphRecord) -> tuple[str, str, int, str]:
    return (
        prop_str(row, "document_id"),
        prop_str(row, "document_version_id"),
        prop_int(row, "ordinal"),
        row.key,
    )


def _card(
    row: GraphRecord,
    classification: ClassificationDefinition,
    centroid: list[float] | None,
) -> QueueCard:
    similarity = None
    if centroid is not None and row.dense_vector is not None:
        if len(row.dense_vector) == len(centroid):
            similarity = cosine_similarity(list(row.dense_vector), centroid)
    return QueueCard(
        unit_id=row.key,
        document_id=prop_str(row, "document_id"),
        document_version_id=prop_str(row, "document_version_id"),
        text=prop_str(row, "text"),
        locator=prop_str(row, "locator") or None,
        ordinal=prop_int(row, "ordinal"),
        section_title=prop_str(row, "section_title") or None,
        content_hash=prop_str(row, "content_hash"),
        classification=classification,
        similarity=similarity,
    )


def _positive_centroid(
    catalog: Catalog,
    scope: KnowledgeTenantScope,
    classification: ClassificationDefinition,
) -> list[float] | None:
    vectors: list[tuple[float, ...]] = []
    for anchor in list_anchors(
        catalog,
        customer_id=scope.customer_id,
        classification_id=classification.id,
        statuses=("draft", "active"),
    ):
        if anchor.polarity != "positive" or anchor.vector is None:
            continue
        vectors.append(anchor.vector)
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


def _labeled_count(session: ReviewSession) -> int:
    return session.decided_yes + session.decided_no + session.skipped + session.unsure
