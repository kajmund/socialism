"""Orchestrate document_find for the workspace find_documents tool."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.document_find.strategies import (
    extend_set,
    filter_to_set,
    find_by_category,
    find_by_hybrid,
    find_category_then_hybrid,
    find_within_documents,
)
from app.services.document_find.taxonomy import (
    NDA_RE,
    TYPE_LABELS_SV,
    TYPE_NEEDLES,
    fold_candidate,
    type_from_user_phrase,
)
from app.services.document_find.types import FindResult, OpCounters
from app.services.overgraph.catalogs import Catalog


@dataclass(frozen=True)
class FindRequest:
    customer_id: int
    query: str
    mode: str
    current: tuple[str, ...] = ()
    dense_query: tuple[float, ...] | None = None
    limit: int = 50
    allowed: frozenset[str] | None = None


@dataclass(frozen=True)
class _FindRequest:
    customer_id: int
    query: str
    mode: str
    current: tuple[str, ...]
    document_type: str | None
    dense_query: tuple[float, ...] | None
    limit: int
    allowed: frozenset[str] | None

_FILLER = re.compile(
    r"\b(visa|alla|dokument|avtal|the|all|show|me|please|bara|dem|med|som|har|and|with|"
    r"only|those|that|have|from|current|selection|urvalet|aktuella)\b|[.?!,]",
    re.IGNORECASE,
)

PRESENTATION_CAP = 40


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


def run_find(catalog: Catalog, request: FindRequest) -> FindResult:
    started = time.perf_counter()
    if request.allowed is not None and not request.allowed:
        return empty_scope_result(request.query)
    current = tuple(
        doc for doc in request.current if request.allowed is None or doc in request.allowed
    )
    mode = normalize_find_mode(request.mode, has_current_set=bool(current), query=request.query)
    inner = _FindRequest(
        customer_id=request.customer_id,
        query=request.query,
        mode=mode,
        current=current,
        document_type=type_from_user_phrase(request.query),
        dense_query=request.dense_query,
        limit=request.limit,
        allowed=request.allowed,
    )
    result = _dispatch(catalog, inner)
    if mode == "extend" and inner.current and "extend" not in result.notes:
        merged = extend_set(inner.current, result.document_ids)
        result = FindResult(
            document_ids=tuple(merged),
            strategy=result.strategy,
            completeness=result.completeness,
            counters=result.counters,
            db_ms=result.db_ms,
            notes=(*result.notes, "extend"),
        )
    return FindResult(
        document_ids=result.document_ids,
        strategy=result.strategy,
        completeness=result.completeness,
        counters=result.counters,
        db_ms=result.db_ms,
        total_ms=(time.perf_counter() - started) * 1000,
        notes=result.notes,
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


def _dispatch(catalog: Catalog, request: _FindRequest) -> FindResult:
    if request.mode in {"within", "filter"} and request.current:
        return _within_or_filter(catalog, request)
    if request.document_type is not None and request.dense_query is None:
        return find_by_category(
            catalog,
            document_type=request.document_type,
            allowed_document_ids=request.allowed,
        )
    if request.document_type is not None and request.dense_query is not None:
        return find_category_then_hybrid(
            catalog,
            customer_id=request.customer_id,
            document_type=request.document_type,
            dense_query=request.dense_query,
            limit=request.limit,
            allowed_document_ids=request.allowed,
        )
    if request.dense_query is None:
        return FindResult(
            document_ids=(),
            strategy="hybrid",
            completeness="uncertain",
            counters=OpCounters(),
            notes=("embedding_required",),
        )
    return find_by_hybrid(
        catalog,
        customer_id=request.customer_id,
        dense_query=request.dense_query,
        limit=request.limit,
        allowed_document_ids=request.allowed,
    )


def _within_or_filter(catalog: Catalog, request: _FindRequest) -> FindResult:
    if request.dense_query is None and request.document_type is not None:
        return filter_to_set(
            find_by_category(
                catalog,
                document_type=request.document_type,
                allowed_document_ids=request.allowed,
            ),
            request.current,
        )
    if request.dense_query is None:
        return FindResult(
            document_ids=request.current,
            strategy="hybrid",
            completeness="uncertain",
            counters=OpCounters(),
            notes=("embedding_required",),
        )
    return find_within_documents(
        catalog,
        customer_id=request.customer_id,
        document_ids=request.current,
        dense_query=request.dense_query,
        limit=request.limit,
        allowed_document_ids=request.allowed,
    )


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
