"""Deterministic document-type classification from title and opening text.

No embeddings, Jev, or LLM. Taxonomy matches the closed experiment contract
without importing experiments/overgraph_ingest.
"""

from __future__ import annotations

from app.services.document_find.taxonomy import (
    CONSULTING,
    LEASE,
    NDA,
    NDA_RE,
    OTHER,
    TYPE_NEEDLES,
    fold_candidate,
)


def classify_document(*, title: str, opening: str = "", headings: str = "") -> str:
    title_fold = fold_candidate(title)
    opening_fold = fold_candidate(opening)
    headings_fold = fold_candidate(headings)
    allow_lease = not _has_any(title_fold, ("kontorshotell", "coworking"))
    for blob in (title_fold, opening_fold, headings_fold):
        matched = _match(blob, allow_lease=allow_lease)
        if matched is not None:
            return matched
    return OTHER


def _match(blob: str, *, allow_lease: bool) -> str | None:
    if "sekretessavtal" in blob or NDA_RE.search(blob):
        return NDA
    for needles, document_type in TYPE_NEEDLES:
        if document_type == LEASE and not allow_lease:
            continue
        if document_type == CONSULTING and "styrelseledamot" in blob:
            continue
        if _has_any(blob, needles):
            return document_type
    return None


def _has_any(blob: str, needles: tuple[str, ...]) -> bool:
    return any(needle in blob for needle in needles)
