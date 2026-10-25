"""Find request contract and pure query policy (no graph imports)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.document_find.taxonomy import (
    NDA_RE,
    TYPE_LABELS_SV,
    TYPE_NEEDLES,
    fold_candidate,
    type_from_user_phrase,
)
from app.services.document_find.types import FindResult, OpCounters

_FILLER = re.compile(
    r"\b(visa|alla|dokument|avtal|the|all|show|me|please|bara|dem|med|som|har|and|with|"
    r"only|those|that|have|from|current|selection|urvalet|aktuella)\b|[.?!,]",
    re.IGNORECASE,
)

PRESENTATION_CAP = 40


@dataclass(frozen=True)
class FindRequest:
    customer_id: int
    query: str
    mode: str
    current: tuple[str, ...] = ()
    dense_query: tuple[float, ...] | None = None
    limit: int = 50
    allowed: frozenset[str] | None = None


def needs_embedding(query: str, *, mode: str, has_current_set: bool) -> bool:
    document_type = type_from_user_phrase(query)
    if document_type is None:
        return True
    if mode in {"within", "filter"} and has_current_set:
        return bool(_content_remainder(query))
    return bool(_content_remainder(query))


def normalize_find_mode(mode: str, *, has_current_set: bool, query: str) -> str:
    """Keep content follow-ups inside the active document set.

    The model authors the search condition. When a document set is already
    active, a content-only query with mode=replace would ignore that set and
    broaden to the whole catalog. Coerce those to filter. Explicit category
    replace/extend/within/filter stay unchanged.
    """
    if mode in {"filter", "within", "extend"} or not has_current_set:
        return mode
    if type_from_user_phrase(query) is None:
        return "filter"
    return mode


def empty_scope_result(query: str) -> FindResult:
    """No readable documents: every strategy completes trivially and honestly."""
    return FindResult(
        document_ids=(),
        strategy="category" if type_from_user_phrase(query) is not None else "hybrid",
        completeness="complete",
        counters=OpCounters(),
        notes=("no_readable_documents",),
    )


def presentation_slice(source_ids: Sequence[str]) -> tuple[list[str], bool]:
    ids = list(source_ids)
    if len(ids) <= PRESENTATION_CAP:
        return ids, False
    return ids[:PRESENTATION_CAP], True


def suggested_title(query: str, result: FindResult) -> str:
    document_type = type_from_user_phrase(query)
    if document_type is not None:
        return TYPE_LABELS_SV.get(document_type, document_type)[:255]
    text = query.strip()
    return (text[:252] + "…") if len(text) > 255 else text or "Dokument"


def _content_remainder(query: str) -> str:
    """Type words and filler removed; empty means a pure category lookup."""
    folded = fold_candidate(query)
    for label in TYPE_LABELS_SV.values():
        folded = re.sub(re.escape(fold_candidate(label)), " ", folded, flags=re.IGNORECASE)
    for needles, _document_type in TYPE_NEEDLES:
        for needle in needles:
            folded = re.sub(re.escape(needle), " ", folded, flags=re.IGNORECASE)
    folded = NDA_RE.sub(" ", folded)
    folded = _FILLER.sub(" ", folded)
    return re.sub(r"\s+", " ", folded).strip()


__all__ = [
    "FindRequest",
    "needs_embedding",
    "normalize_find_mode",
    "empty_scope_result",
    "presentation_slice",
    "suggested_title",
]
