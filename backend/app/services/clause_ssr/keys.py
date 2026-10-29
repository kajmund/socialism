"""Stable OverGraph keys for clause SSR nodes."""

from __future__ import annotations

from app.services.graph_v2.identity import stable_id


def classification_key(scope_key: str, slug: str, version: int) -> str:
    return f"{scope_key}:cls:{slug}:v{version}"


def verification_key(
    scope_key: str,
    classification_id: str,
    unit_id: str,
    reviewer_id: str,
) -> str:
    return stable_id("ssr.ver", scope_key, classification_id, unit_id, reviewer_id)


def revision_key(verification_id: str, revision: int) -> str:
    return f"{verification_id}:rev:{revision}"


def anchor_key(scope_key: str, verification_id: str) -> str:
    return stable_id("ssr.anc", scope_key, verification_id)


def set_key(scope_key: str, category: str, version: int) -> str:
    return f"{scope_key}:aset:{category}:v{version}"


def session_key(
    scope_key: str,
    reviewer_id: str,
    classification_id: str,
    document_id: str | None,
) -> str:
    return stable_id("ssr.ses", scope_key, reviewer_id, classification_id, document_id or "")


def review_key(classification_id: str, reviewer_id: str) -> str:
    return f"{classification_id}:{reviewer_id}"
