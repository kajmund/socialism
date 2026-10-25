"""Owner-backed document find for one tenant knowledge catalog.

The backend keeps the find strategy; every graph read goes through the Owner.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.document_find.category_index import category_key_for_type
from app.services.document_find.group import dedupe_document_ids, document_ids_from_hits
from app.services.document_find.labels import (
    CANONICAL_DOCUMENT,
    DOCUMENT_CATEGORY,
    DOCUMENT_VERSION,
    HAS_VERSION,
)
from app.services.document_find.taxonomy import type_from_user_phrase
from app.services.document_find.request import (
    FindRequest,
    empty_scope_result,
    normalize_find_mode,
)
from app.services.document_find.types import FindResult, OpCounters
from app.services.document_qa.owner_document_index import documents_for_type
from app.services.overgraph.model import KnowledgeHit
from app.services.overgraph.owner import OwnerClient


@dataclass(frozen=True)
class _Request:
    customer_id: int
    query: str
    mode: str
    current: tuple[str, ...]
    document_type: str | None
    dense_query: tuple[float, ...] | None
    limit: int
    allowed: frozenset[str] | None


def _hit(row: dict) -> KnowledgeHit:
    return KnowledgeHit(
        key=str(row["key"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        score=float(row.get("score") or 0.0),
        scope_key=str(row.get("scope_key") or ""),
        text=str(row.get("text") or ""),
        props=dict(row.get("props") or {}),
        hop=int(row.get("hop") or 0),
    )


def _count(hits: Sequence[KnowledgeHit]) -> int:
    return sum(1 for hit in hits if hit.kind == "text_unit")


async def _current_version_keys(
    client: OwnerClient,
    document_ids: Sequence[str],
) -> dict[str, str]:
    rows = await client.related_nodes(
        [{"label": CANONICAL_DOCUMENT, "key": document_id} for document_id in document_ids],
        HAS_VERSION,
        child_label=DOCUMENT_VERSION,
        limit=20,
    )
    versions: dict[str, str] = {}
    for row in rows:
        versions.setdefault(str(row["parent_key"]), str(row["key"]))
    return versions


async def find_by_category(
    client: OwnerClient,
    *,
    document_type: str | None = None,
    user_phrase: str | None = None,
    allowed_document_ids: Sequence[str] | None = None,
) -> FindResult:
    started = time.perf_counter()
    ops = OpCounters()
    resolved = document_type or (type_from_user_phrase(user_phrase or "") if user_phrase else None)
    if resolved is None:
        return FindResult(
            document_ids=(),
            strategy="category",
            completeness="uncertain",
            counters=ops,
            notes=("unknown_category",),
            total_ms=(time.perf_counter() - started) * 1000,
        )
    db_started = time.perf_counter()
    ids = await documents_for_type(client, resolved)
    ops.category_lookups += 1
    if allowed_document_ids is not None:
        allowed = set(allowed_document_ids)
        ids = [document_id for document_id in ids if document_id in allowed]
    return FindResult(
        document_ids=tuple(ids),
        strategy="category",
        completeness="complete",
        counters=ops,
        db_ms=(time.perf_counter() - db_started) * 1000,
        total_ms=(time.perf_counter() - started) * 1000,
    )


async def find_by_hybrid(
    client: OwnerClient,
    *,
    customer_id: int,
    dense_query: Sequence[float],
    limit: int = 50,
    allowed_document_ids: Sequence[str] | None = None,
) -> FindResult:
    started = time.perf_counter()
    ops = OpCounters()
    allowed = frozenset(allowed_document_ids) if allowed_document_ids is not None else None
    fetch = limit * 4 if allowed is not None else limit
    db_started = time.perf_counter()
    ops.vector_searches += 1
    hits = [
        _hit(row)
        for row in await client.hybrid_search(
            customer_id=customer_id,
            dense_query=list(dense_query),
            limit=fetch,
        )
    ]
    ops.text_unit_reads += _count(hits)
    if allowed is not None:
        hits = [hit for hit in hits if str(hit.props.get("document_id") or "") in allowed]
    ids = document_ids_from_hits(hits)[:limit]
    return FindResult(
        document_ids=tuple(ids),
        strategy="hybrid",
        completeness="partial",
        counters=ops,
        db_ms=(time.perf_counter() - db_started) * 1000,
        total_ms=(time.perf_counter() - started) * 1000,
    )


async def find_category_then_hybrid(
    client: OwnerClient,
    *,
    customer_id: int,
    document_type: str,
    dense_query: Sequence[float],
    limit: int = 50,
    mode: str = "scoped_per_document",
    allowed_document_ids: Sequence[str] | None = None,
) -> FindResult:
    started = time.perf_counter()
    category = await find_by_category(client, document_type=document_type)
    allowed = set(category.document_ids)
    if allowed_document_ids is not None:
        allowed &= set(allowed_document_ids)
    if not allowed:
        notes = ("empty_category",) if not category.document_ids else ("no_readable_documents",)
        return FindResult(
            document_ids=(),
            strategy="category_hybrid",
            completeness="complete",
            counters=category.counters,
            db_ms=category.db_ms,
            total_ms=(time.perf_counter() - started) * 1000,
            notes=notes,
        )
    ops = category.counters
    db_started = time.perf_counter()
    if mode == "scoped_from_category":
        ids, mode_ops = await _scoped_from_category(
            client,
            customer_id=customer_id,
            document_type=document_type,
            dense_query=dense_query,
            limit=limit,
            allowed=allowed,
        )
    elif mode == "scoped_per_document":
        ids, mode_ops = await _scoped_per_document(
            client,
            customer_id=customer_id,
            dense_query=dense_query,
            limit=limit,
            allowed=allowed,
        )
    else:
        ids, mode_ops = await _global_post_filter(
            client,
            customer_id=customer_id,
            dense_query=dense_query,
            limit=limit,
            allowed=allowed,
        )
    return FindResult(
        document_ids=tuple(ids),
        strategy="category_hybrid",
        completeness="partial",
        counters=ops.add(mode_ops),
        db_ms=category.db_ms + (time.perf_counter() - db_started) * 1000,
        total_ms=(time.perf_counter() - started) * 1000,
        notes=(mode,),
    )


async def find_within_documents(
    client: OwnerClient,
    *,
    customer_id: int,
    document_ids: Sequence[str],
    dense_query: Sequence[float],
    limit: int = 50,
    allowed_document_ids: Sequence[str] | None = None,
) -> FindResult:
    started = time.perf_counter()
    allowed = {document_id for document_id in document_ids if document_id}
    if allowed_document_ids is not None:
        allowed &= set(allowed_document_ids)
    if not allowed:
        return FindResult(
            document_ids=(),
            strategy="hybrid",
            completeness="complete",
            counters=OpCounters(),
            notes=("within_set", "empty_set"),
            total_ms=(time.perf_counter() - started) * 1000,
        )
    db_started = time.perf_counter()
    ids, ops = await _scoped_per_document(
        client,
        customer_id=customer_id,
        dense_query=dense_query,
        limit=limit,
        allowed=allowed,
    )
    return FindResult(
        document_ids=tuple(ids),
        strategy="hybrid",
        completeness="partial",
        counters=ops,
        db_ms=(time.perf_counter() - db_started) * 1000,
        total_ms=(time.perf_counter() - started) * 1000,
        notes=("within_set", "scoped_per_document"),
    )


async def _scoped_from_category(
    client: OwnerClient,
    *,
    customer_id: int,
    document_type: str,
    dense_query: Sequence[float],
    limit: int,
    allowed: set[str],
) -> tuple[list[str], OpCounters]:
    ops = OpCounters()
    hits = [
        _hit(row)
        for row in await client.scoped_search(
            customer_id=customer_id,
            start_label=DOCUMENT_CATEGORY,
            start_key=category_key_for_type(document_type),
            dense_query=list(dense_query),
            max_depth=4,
            limit=limit,
        )
    ]
    ops.vector_searches += 1
    ops.text_unit_reads += _count(hits)
    return [doc for doc in document_ids_from_hits(hits) if doc in allowed], ops


async def _scoped_per_document(
    client: OwnerClient,
    *,
    customer_id: int,
    dense_query: Sequence[float],
    limit: int,
    allowed: set[str],
) -> tuple[list[str], OpCounters]:
    ops = OpCounters()
    versions = await _current_version_keys(client, sorted(allowed))
    ops.neighbor_lookups += 1
    per_doc = max(1, limit // max(1, len(allowed)))
    scored: dict[str, float] = {}
    for document_id in sorted(allowed):
        version_key = versions.get(document_id)
        if version_key is None:
            continue
        hits = [
            _hit(row)
            for row in await client.scoped_search(
                customer_id=customer_id,
                start_label=DOCUMENT_VERSION,
                start_key=version_key,
                dense_query=list(dense_query),
                max_depth=2,
                limit=per_doc,
            )
        ]
        ops.vector_searches += 1
        ops.text_unit_reads += _count(hits)
        for hit in hits:
            document_id_hit = str(hit.props.get("document_id") or "")
            if document_id_hit in allowed:
                scored[document_id_hit] = max(scored.get(document_id_hit, 0.0), hit.score)
    ordered = sorted(scored, key=lambda key: scored[key], reverse=True)[:limit]
    return ordered, ops


async def _global_post_filter(
    client: OwnerClient,
    *,
    customer_id: int,
    dense_query: Sequence[float],
    limit: int,
    allowed: set[str],
) -> tuple[list[str], OpCounters]:
    ops = OpCounters()
    hits = [
        _hit(row)
        for row in await client.hybrid_search(
            customer_id=customer_id,
            dense_query=list(dense_query),
            limit=limit,
        )
    ]
    ops.vector_searches += 1
    ops.text_unit_reads += _count(hits)
    return [doc for doc in document_ids_from_hits(hits) if doc in allowed], ops


def _within_or_filter(request: _Request) -> str:
    if request.dense_query is None and request.document_type is not None:
        return "filter"
    if request.dense_query is None:
        return "embedding_required"
    return "within"


async def run_find(client: OwnerClient, request: FindRequest) -> FindResult:
    """Owner-backed equivalent of ``document_find.tool.run_find``."""
    started = time.perf_counter()
    if request.allowed is not None and not request.allowed:
        return empty_scope_result(request.query)
    current = tuple(
        document_id
        for document_id in request.current
        if request.allowed is None or document_id in request.allowed
    )
    mode = normalize_find_mode(
        request.mode,
        has_current_set=bool(current),
        query=request.query,
    )
    inner = _Request(
        customer_id=request.customer_id,
        query=request.query,
        mode=mode,
        current=current,
        document_type=type_from_user_phrase(request.query),
        dense_query=request.dense_query,
        limit=request.limit,
        allowed=request.allowed,
    )
    result = await _dispatch(client, inner)
    if mode == "extend" and inner.current and "extend" not in result.notes:
        result = FindResult(
            document_ids=tuple(dedupe_document_ids([*inner.current, *result.document_ids])),
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


async def _dispatch(client: OwnerClient, request: _Request) -> FindResult:
    if request.mode in {"within", "filter"} and request.current:
        return await _within_dispatch(client, request)
    return await _content_dispatch(client, request)


async def _within_dispatch(client: OwnerClient, request: _Request) -> FindResult:
    kind = _within_or_filter(request)
    if kind == "filter":
        result = await find_by_category(
            client,
            document_type=request.document_type,
            allowed_document_ids=request.allowed,
        )
        current = set(request.current)
        return FindResult(
            document_ids=tuple(
                document_id for document_id in result.document_ids if document_id in current
            ),
            strategy=result.strategy,
            completeness=result.completeness,
            counters=result.counters,
            db_ms=result.db_ms,
            total_ms=result.total_ms,
            notes=(*result.notes, "within_set"),
        )
    if kind == "embedding_required":
        return FindResult(
            document_ids=request.current,
            strategy="hybrid",
            completeness="uncertain",
            counters=OpCounters(),
            notes=("embedding_required",),
        )
    return await find_within_documents(
        client,
        customer_id=request.customer_id,
        document_ids=request.current,
        dense_query=request.dense_query or (),
        limit=request.limit,
        allowed_document_ids=request.allowed,
    )


async def _content_dispatch(client: OwnerClient, request: _Request) -> FindResult:
    if request.document_type is not None and request.dense_query is None:
        return await find_by_category(
            client,
            document_type=request.document_type,
            allowed_document_ids=request.allowed,
        )
    if request.document_type is not None and request.dense_query is not None:
        return await find_category_then_hybrid(
            client,
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
    return await find_by_hybrid(
        client,
        customer_id=request.customer_id,
        dense_query=request.dense_query,
        limit=request.limit,
        allowed_document_ids=request.allowed,
    )
