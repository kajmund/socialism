"""Human YES/NO (and skip/unsure) decisions. Skip/unsure are not labels."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.isolation import assert_visible, can_reference
from app.services.overgraph.labels import TEXT_UNIT
from app.services.overgraph.model import GraphRecord

from app.services.clause_ssr.classifications import get_classification
from app.services.clause_ssr.graph import (
    find_by_prop,
    link,
    now_ms,
    prop_int,
    prop_str,
    require_node,
    upsert_scoped,
)
from app.services.clause_ssr.keys import review_key, revision_key, verification_key
from app.services.clause_ssr.labels import (
    ABOUT,
    ANSWERS as ANSWERS_EDGE,
    CLASSIFICATION,
    SUPERSEDES,
    VERIFICATION,
    VERIFICATION_REVISION,
)
from app.services.clause_ssr.types import (
    ANSWERS,
    LABEL_ANSWERS,
    DecisionAnswer,
    Polarity,
    Verification,
    VerificationWrite,
)


def polarity_for(answer: DecisionAnswer) -> Polarity | None:
    if answer == "yes":
        return "positive"
    if answer == "no":
        return "negative"
    return None


def record_decision(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    classification_id: str,
    unit_id: str,
    reviewer_id: str,
    answer: DecisionAnswer,
    source: str = "admin_queue",
) -> Verification:
    if answer not in ANSWERS:
        raise ValueError(f"unknown decision answer: {answer}")
    classification = get_classification(catalog, classification_id)
    if not can_reference(scope, classification.scope_key):
        raise PermissionError("classification is outside the caller tenant")
    unit = require_node(catalog, TEXT_UNIT, unit_id)
    assert_visible(prop_str(unit, "scope_key"), scope.customer_id)
    key = verification_key(scope.scope_key, classification_id, unit_id, reviewer_id)
    existing = catalog.get_by_key(VERIFICATION, key)
    revision = 1
    if existing is not None:
        current = _from_row(existing)
        if current.status == "active" and current.answer == answer:
            return current
        if current.status == "active":
            _archive_revision(catalog, current, scope)
        revision = current.revision + 1
    payload = VerificationWrite(
        key=key,
        unit_id=unit.key,
        document_id=prop_str(unit, "document_id"),
        content_hash=prop_str(unit, "content_hash"),
        classification_id=classification.id,
        classification_version=classification.version,
        question=classification.question,
        category=classification.category,
        answer=answer,
        reviewer_id=reviewer_id,
        source=source,
        revision=revision,
        status="active",
    )
    row = _write_verification(catalog, payload, scope)
    link(catalog, row, require_node(catalog, CLASSIFICATION, classification.id), label=ABOUT)
    link(catalog, row, unit, label=ANSWERS_EDGE)
    return _from_row(row)


def revoke_verification(
    catalog: Catalog,
    verification_id: str,
    *,
    scope: KnowledgeTenantScope,
) -> Verification:
    current = get_verification(catalog, verification_id)
    if current.scope_key != scope.scope_key:
        raise PermissionError("verification is outside the caller tenant")
    payload = VerificationWrite(
        key=current.id,
        unit_id=current.source_unit_id,
        document_id=current.source_document_id,
        content_hash=current.content_hash,
        classification_id=current.classification_id,
        classification_version=current.classification_version,
        question=current.question,
        category=current.category,
        answer=current.answer,
        reviewer_id=current.reviewer_id,
        source=current.source,
        revision=current.revision,
        status="revoked",
        decided_at_ms=current.decided_at_ms,
    )
    return _from_row(_write_verification(catalog, payload, scope))


def get_verification(catalog: Catalog, verification_id: str) -> Verification:
    return _from_row(require_node(catalog, VERIFICATION, verification_id))


def list_reviewer_decisions(
    catalog: Catalog,
    *,
    classification_id: str,
    reviewer_id: str,
) -> list[Verification]:
    items: list[Verification] = []
    for row in find_by_prop(
        catalog, VERIFICATION, "review_key", review_key(classification_id, reviewer_id),
    ):
        item = _from_row(row)
        if item.status == "active":
            items.append(item)
    return items


def _archive_revision(
    catalog: Catalog, current: Verification, scope: KnowledgeTenantScope,
) -> None:
    upsert_scoped(
        catalog,
        kind=VERIFICATION_REVISION,
        key=revision_key(current.id, current.revision),
        scope=scope,
        props={
            "verification_id": current.id,
            "source_unit_id": current.source_unit_id,
            "source_document_id": current.source_document_id,
            "content_hash": current.content_hash,
            "classification_id": current.classification_id,
            "classification_version": current.classification_version,
            "question": current.question,
            "category": current.category,
            "answer": current.answer,
            "polarity": current.polarity or "",
            "reviewer_id": current.reviewer_id,
            "decided_at_ms": current.decided_at_ms,
            "source": current.source,
            "revision": current.revision,
            "status": "superseded",
            "review_key": review_key(current.classification_id, current.reviewer_id),
        },
    )
    archived = require_node(
        catalog, VERIFICATION_REVISION, revision_key(current.id, current.revision),
    )
    link(catalog, require_node(catalog, VERIFICATION, current.id), archived, label=SUPERSEDES)


def _write_verification(
    catalog: Catalog, payload: VerificationWrite, scope: KnowledgeTenantScope,
) -> GraphRecord:
    polarity = polarity_for(payload.answer)
    return upsert_scoped(
        catalog,
        kind=VERIFICATION,
        key=payload.key,
        scope=scope,
        props={
            "source_unit_id": payload.unit_id,
            "source_document_id": payload.document_id,
            "content_hash": payload.content_hash,
            "classification_id": payload.classification_id,
            "classification_version": payload.classification_version,
            "question": payload.question,
            "category": payload.category,
            "answer": payload.answer,
            "polarity": polarity or "",
            "reviewer_id": payload.reviewer_id,
            "decided_at_ms": payload.decided_at_ms or now_ms(),
            "source": payload.source,
            "revision": payload.revision,
            "status": payload.status,
            "review_key": review_key(payload.classification_id, payload.reviewer_id),
            "labeled": payload.answer in LABEL_ANSWERS,
        },
    )


def _from_row(row: GraphRecord) -> Verification:
    answer = prop_str(row, "answer")
    if answer not in ANSWERS:
        raise ValueError(f"corrupt verification answer: {answer}")
    polarity_raw = prop_str(row, "polarity")
    polarity: Polarity | None = None
    if polarity_raw in {"positive", "negative"}:
        polarity = polarity_raw  # type: ignore[assignment]
    status = prop_str(row, "status") or "active"
    return Verification(
        id=row.key,
        source_unit_id=prop_str(row, "source_unit_id"),
        source_document_id=prop_str(row, "source_document_id"),
        content_hash=prop_str(row, "content_hash"),
        classification_id=prop_str(row, "classification_id"),
        classification_version=prop_int(row, "classification_version", 1),
        question=prop_str(row, "question"),
        category=prop_str(row, "category"),
        answer=answer,  # type: ignore[arg-type]
        polarity=polarity,
        reviewer_id=prop_str(row, "reviewer_id"),
        decided_at_ms=prop_int(row, "decided_at_ms"),
        source=prop_str(row, "source") or "admin_queue",
        revision=prop_int(row, "revision", 1),
        status=status,  # type: ignore[arg-type]
        scope_key=prop_str(row, "scope_key"),
    )
