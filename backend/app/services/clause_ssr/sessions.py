"""Reviewer queue sessions so a run can resume without losing answers."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord

from app.services.clause_ssr.graph import link, prop_int, prop_str, upsert_scoped
from app.services.clause_ssr.keys import session_key
from app.services.clause_ssr.labels import CLASSIFICATION, FOR, REVIEW_SESSION
from app.services.clause_ssr.types import ReviewSession, Verification
from app.services.clause_ssr.verifications import list_reviewer_decisions, revoke_verification


def get_or_create_session(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    reviewer_id: str,
    classification_id: str,
    document_id: str | None = None,
) -> ReviewSession:
    key = session_key(scope.scope_key, reviewer_id, classification_id, document_id)
    existing = catalog.get_by_key(REVIEW_SESSION, key)
    if existing is not None:
        return _from_row(existing)
    row = upsert_scoped(
        catalog,
        kind=REVIEW_SESSION,
        key=key,
        scope=scope,
        props=_session_props(
            reviewer_id=reviewer_id,
            classification_id=classification_id,
            document_id=document_id,
            last_unit_id=None,
            last_verification_id=None,
            counts={"yes": 0, "no": 0, "skip": 0, "unsure": 0},
        ),
    )
    classification = catalog.get_by_key(CLASSIFICATION, classification_id)
    if classification is not None:
        link(catalog, row, classification, label=FOR)
    return _from_row(row)


def apply_decision(
    catalog: Catalog,
    session: ReviewSession,
    verification: Verification,
    *,
    scope: KnowledgeTenantScope,
) -> ReviewSession:
    return _save(
        catalog,
        session=session,
        scope=scope,
        verification=verification,
        counts=_recount(catalog, session),
    )


def undo_last(
    catalog: Catalog,
    session: ReviewSession,
    *,
    scope: KnowledgeTenantScope,
) -> tuple[ReviewSession, str | None]:
    if not session.last_verification_id:
        return session, None
    revoked = revoke_verification(catalog, session.last_verification_id, scope=scope)
    updated = _save(
        catalog,
        session=session,
        scope=scope,
        verification=None,
        counts=_recount(catalog, session),
    )
    return updated, revoked.source_unit_id


def _recount(catalog: Catalog, session: ReviewSession) -> dict[str, int]:
    counts = {"yes": 0, "no": 0, "skip": 0, "unsure": 0}
    for item in list_reviewer_decisions(
        catalog,
        classification_id=session.classification_id,
        reviewer_id=session.reviewer_id,
    ):
        if session.document_id and item.source_document_id != session.document_id:
            continue
        counts[item.answer] = counts.get(item.answer, 0) + 1
    return counts


def _save(
    catalog: Catalog,
    *,
    session: ReviewSession,
    scope: KnowledgeTenantScope,
    verification: Verification | None,
    counts: dict[str, int],
) -> ReviewSession:
    row = upsert_scoped(
        catalog,
        kind=REVIEW_SESSION,
        key=session.id,
        scope=scope,
        props=_session_props(
            reviewer_id=session.reviewer_id,
            classification_id=session.classification_id,
            document_id=session.document_id,
            last_unit_id=verification.source_unit_id if verification else None,
            last_verification_id=verification.id if verification else None,
            counts=counts,
        ),
    )
    return _from_row(row)


def _session_props(
    *,
    reviewer_id: str,
    classification_id: str,
    document_id: str | None,
    last_unit_id: str | None,
    last_verification_id: str | None,
    counts: dict[str, int],
) -> dict[str, object]:
    return {
        "reviewer_id": reviewer_id,
        "classification_id": classification_id,
        "document_id": document_id or "",
        "last_unit_id": last_unit_id or "",
        "last_verification_id": last_verification_id or "",
        "decided_yes": counts.get("yes", 0),
        "decided_no": counts.get("no", 0),
        "skipped": counts.get("skip", 0),
        "unsure": counts.get("unsure", 0),
    }


def _from_row(row: GraphRecord) -> ReviewSession:
    return ReviewSession(
        id=row.key,
        reviewer_id=prop_str(row, "reviewer_id"),
        classification_id=prop_str(row, "classification_id"),
        document_id=prop_str(row, "document_id") or None,
        last_unit_id=prop_str(row, "last_unit_id") or None,
        last_verification_id=prop_str(row, "last_verification_id") or None,
        decided_yes=prop_int(row, "decided_yes"),
        decided_no=prop_int(row, "decided_no"),
        skipped=prop_int(row, "skipped"),
        unsure=prop_int(row, "unsure"),
        scope_key=prop_str(row, "scope_key"),
    )
