"""Orchestrate document_find for the workspace find_documents tool."""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.services.document_find.request import (
    FindRequest,
    empty_scope_result,
    normalize_find_mode,
)
from app.services.document_find.strategies import (
    extend_set,
    filter_to_set,
    find_by_category,
    find_by_hybrid,
    find_category_then_hybrid,
    find_within_documents,
)
from app.services.document_find.taxonomy import type_from_user_phrase
from app.services.document_find.types import FindResult, OpCounters
from app.services.overgraph.catalogs import Catalog


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
