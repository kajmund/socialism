"""Draft clause anchors derived from labeled verifications. Never auto-promoted."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import TEXT_UNIT
from app.services.overgraph.model import GraphRecord

from app.services.clause_ssr.graph import (
    find_by_prop,
    link,
    list_visible,
    prop_int,
    prop_str,
    require_node,
    upsert_scoped,
)
from app.services.clause_ssr.keys import anchor_key
from app.services.clause_ssr.labels import ANCHOR, DERIVED_FROM, REPRESENTS, VERIFICATION
from app.services.clause_ssr.types import (
    LABEL_ANSWERS,
    Anchor,
    AnchorStatus,
    EmbeddingSpec,
    Polarity,
    Verification,
)
from app.services.clause_ssr.verifications import (
    get_verification,
    polarity_for,
    revoke_verification,
)


def promote_anchor(
    catalog: Catalog,
    verification_id: str,
    *,
    scope: KnowledgeTenantScope,
    embedding: EmbeddingSpec,
) -> Anchor:
    verification = get_verification(catalog, verification_id)
    if verification.scope_key != scope.scope_key:
        raise PermissionError("verification is outside the caller tenant")
    if verification.status != "active" or verification.answer not in LABEL_ANSWERS:
        raise ValueError("only active yes/no verifications can become anchors")
    polarity = polarity_for(verification.answer)
    if polarity is None:
        raise ValueError("skip/unsure cannot become anchors")
    key = anchor_key(scope.scope_key, verification.id)
    existing = catalog.get_by_key(ANCHOR, key)
    if existing is not None:
        current = _from_row(existing)
        if current.status not in {"revoked", "source_revoked"}:
            if not _verification_is_valid(get_verification(catalog, verification.id), polarity):
                revoke_anchor(catalog, current.id, scope=scope, status="revoked")
                raise ValueError("verification is no longer active")
            return current
    unit = require_node(catalog, TEXT_UNIT, verification.source_unit_id)
    vector = _unit_vector(unit, embedding)
    status: AnchorStatus = "draft" if vector is not None else "stale_embedding"
    row = _write_anchor(
        catalog,
        key=key,
        scope=scope,
        verification=verification,
        polarity=polarity,
        embedding=embedding,
        status=status,
    )
    if vector is not None:
        catalog.upsert_node(
            list(row.labels),
            row.key,
            props=dict(row.props),
            dense_vector=list(vector),
        )
        row = require_node(catalog, ANCHOR, key)
    link(catalog, row, require_node(catalog, VERIFICATION, verification.id), label=DERIVED_FROM)
    link(catalog, row, unit, label=REPRESENTS)
    fresh = get_verification(catalog, verification.id)
    if not _verification_is_valid(fresh, polarity):
        revoke_anchor(catalog, row.key, scope=scope, status="revoked")
        raise ValueError("verification is no longer active")
    return _from_row(row)


def revoke_anchor(
    catalog: Catalog, anchor_id: str, *, scope: KnowledgeTenantScope, status: AnchorStatus,
) -> Anchor:
    current = get_anchor(catalog, anchor_id)
    if current.scope_key != scope.scope_key:
        raise PermissionError("anchor is outside the caller tenant")
    verification = get_verification(catalog, current.verification_id)
    polarity = current.polarity
    row = _write_anchor(
        catalog,
        key=current.id,
        scope=scope,
        verification=verification,
        polarity=polarity,
        embedding=current.embedding,
        status=status,
    )
    return _from_row(row)


def get_anchor(catalog: Catalog, anchor_id: str) -> Anchor:
    return _from_row(require_node(catalog, ANCHOR, anchor_id))


def list_anchors(
    catalog: Catalog,
    *,
    customer_id: int | None,
    classification_id: str | None = None,
    statuses: tuple[AnchorStatus, ...] = ("draft", "active"),
) -> list[Anchor]:
    items = [_from_row(row) for row in list_visible(catalog, ANCHOR, customer_id)]
    if classification_id is not None:
        items = [item for item in items if item.classification_id == classification_id]
    allowed = set(statuses)
    return [item for item in items if item.status in allowed]


def mark_stale_embeddings(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    expected: EmbeddingSpec,
) -> int:
    changed = 0
    for item in list_anchors(catalog, customer_id=scope.customer_id, statuses=(
        "draft", "active", "stale_embedding",
    )):
        if item.scope_key != scope.scope_key:
            continue
        if _same_embedding(item.embedding, expected):
            continue
        revoke_anchor(catalog, item.id, scope=scope, status="stale_embedding")
        changed += 1
    return changed


def revoke_source_unit(
    catalog: Catalog, unit_id: str, *, scope: KnowledgeTenantScope,
) -> int:
    changed = 0
    for row in find_by_prop(catalog, ANCHOR, "source_unit_id", unit_id):
        item = _from_row(row)
        if item.scope_key != scope.scope_key:
            continue
        revoke_anchor(catalog, item.id, scope=scope, status="source_revoked")
        changed += 1
    for row in find_by_prop(catalog, VERIFICATION, "source_unit_id", unit_id):
        if prop_str(row, "scope_key") != scope.scope_key:
            continue
        revoke_verification(catalog, row.key, scope=scope)
    return changed


def _write_anchor(
    catalog: Catalog,
    *,
    key: str,
    scope: KnowledgeTenantScope,
    verification: Verification,
    polarity: Polarity,
    embedding: EmbeddingSpec,
    status: AnchorStatus,
) -> GraphRecord:
    return upsert_scoped(
        catalog,
        kind=ANCHOR,
        key=key,
        scope=scope,
        props={
            "verification_id": verification.id,
            "source_unit_id": verification.source_unit_id,
            "classification_id": verification.classification_id,
            "category": verification.category,
            "polarity": polarity,
            "content_hash": verification.content_hash,
            "status": status,
            "embedding_model": embedding.model,
            "embedding_revision": embedding.revision,
            "embedding_dimension": embedding.dimension,
            "reviewer_id": verification.reviewer_id,
            "question": verification.question,
        },
    )


def _unit_vector(unit: GraphRecord, embedding: EmbeddingSpec) -> list[float] | None:
    if unit.dense_vector is None:
        return None
    if len(unit.dense_vector) != embedding.dimension:
        return None
    return list(unit.dense_vector)


def _same_embedding(left: EmbeddingSpec, right: EmbeddingSpec) -> bool:
    return (
        left.model == right.model
        and left.revision == right.revision
        and left.dimension == right.dimension
    )


def _from_row(row: GraphRecord) -> Anchor:
    polarity = prop_str(row, "polarity")
    if polarity not in {"positive", "negative"}:
        raise ValueError(f"corrupt anchor polarity: {polarity}")
    vector = tuple(row.dense_vector) if row.dense_vector else None
    return Anchor(
        id=row.key,
        verification_id=prop_str(row, "verification_id"),
        source_unit_id=prop_str(row, "source_unit_id"),
        classification_id=prop_str(row, "classification_id"),
        category=prop_str(row, "category"),
        polarity=polarity,  # type: ignore[arg-type]
        content_hash=prop_str(row, "content_hash"),
        status=prop_str(row, "status") or "draft",  # type: ignore[arg-type]
        embedding=EmbeddingSpec(
            model=prop_str(row, "embedding_model"),
            revision=prop_str(row, "embedding_revision"),
            dimension=prop_int(row, "embedding_dimension"),
        ),
        vector=vector,
        scope_key=prop_str(row, "scope_key"),
        provenance={
            "reviewer_id": prop_str(row, "reviewer_id"),
            "question": prop_str(row, "question"),
        },
    )


def anchor_is_matchable(catalog: Catalog, anchor: Anchor) -> bool:
    """Read-side guard: never match an anchor whose verification is invalid."""
    try:
        verification = get_verification(catalog, anchor.verification_id)
    except KeyError:
        return False
    return verification.status == "active" and _verification_is_valid(
        verification, anchor.polarity
    )


def revoke_anchors_for_verification(
    catalog: Catalog,
    verification_id: str,
    *,
    scope: KnowledgeTenantScope,
) -> int:
    """Cheap cascade: revoke derived anchors without rebuilding anchor sets."""
    changed = 0
    for row in find_by_prop(catalog, ANCHOR, "verification_id", verification_id):
        item = _from_row(row)
        if item.scope_key != scope.scope_key:
            continue
        if item.status in {"revoked", "source_revoked"}:
            continue
        revoke_anchor(catalog, item.id, scope=scope, status="revoked")
        changed += 1
    return changed


def _verification_is_valid(verification: Verification, polarity: Polarity) -> bool:
    return (
        verification.status == "active"
        and verification.answer in LABEL_ANSWERS
        and verification.polarity == polarity
    )
