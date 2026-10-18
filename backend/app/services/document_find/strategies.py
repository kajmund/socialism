"""Adaptive document find strategies against tenant OverGraph."""

from __future__ import annotations

import time
from collections.abc import Collection, Sequence

from app.services.document_find.category_index import (
    apply_effective_type,
    category_key_for_type,
    documents_for_type,
)
from app.services.document_find.classify import classify_document
from app.services.document_find.group import dedupe_document_ids, document_ids_from_hits
from app.services.document_find.labels import (
    CANONICAL_DOCUMENT,
    DOCUMENT_CATEGORY,
    DOCUMENT_VERSION,
    HAS_VERSION,
)
from app.services.document_find.taxonomy import require_type, type_from_user_phrase
from app.services.document_find.types import FindResult, OpCounters, ScopedMode
from app.services.graph_v2.types import NodeInput
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import OBJECT, SUBJECT
from app.services.overgraph.retrieval import hybrid_search, scoped_search
from app.services.overgraph.write import upsert_entity


def classify_and_index(
    catalog: Catalog,
    *,
    document_id: str,
    title: str,
    opening: str = "",
    headings: str = "",
    counters: OpCounters | None = None,
) -> str:
    """Full chain step: classify text → write effective_type + category index."""
    ops = counters or OpCounters()
    document_type = classify_document(title=title, opening=opening, headings=headings)
    apply_effective_type(
        catalog, document_id=document_id, document_type=document_type, counters=ops,
    )
    return document_type


def find_by_category(
    catalog: Catalog,
    *,
    document_type: str | None = None,
    user_phrase: str | None = None,
    allowed_document_ids: Collection[str] | None = None,
) -> FindResult:
    """Strategy A: indexed category lookup. Zero embeddings / Jev / TextUnits."""
    started = time.perf_counter()
    ops = OpCounters()
    resolved = document_type or (
        type_from_user_phrase(user_phrase or "") if user_phrase else None
    )
    if resolved is None:
        return FindResult(
            document_ids=(),
            strategy="category",
            completeness="uncertain",
            counters=ops,
            db_ms=0.0,
            total_ms=(time.perf_counter() - started) * 1000,
            notes=("unknown_category",),
        )
    require_type(resolved)
    db_started = time.perf_counter()
    ids = documents_for_type(catalog, resolved, counters=ops)
    if allowed_document_ids is not None:
        allowed = frozenset(allowed_document_ids)
        ids = [doc for doc in ids if doc in allowed]
    db_ms = (time.perf_counter() - db_started) * 1000
    return FindResult(
        document_ids=tuple(ids),
        strategy="category",
        completeness="complete",
        counters=ops,
        db_ms=db_ms,
        total_ms=(time.perf_counter() - started) * 1000,
    )


def find_by_hybrid(
    catalog: Catalog,
    *,
    customer_id: int,
    dense_query: Sequence[float],
    limit: int = 50,
    allowed_document_ids: Collection[str] | None = None,
) -> FindResult:
    """Strategy B: dense/hybrid retrieval → group by document_id.

    Unreadable hits are dropped before grouping, so fetch a wider window when
    a readable scope is given and truncate back to `limit` afterwards.
    """
    started = time.perf_counter()
    ops = OpCounters()
    ops.vector_searches += 1
    allowed = frozenset(allowed_document_ids) if allowed_document_ids is not None else None
    fetch = limit * 4 if allowed is not None else limit
    db_started = time.perf_counter()
    hits = hybrid_search(
        catalog, customer_id=customer_id, dense_query=dense_query, limit=fetch,
    )
    ops.text_unit_reads += sum(1 for hit in hits if hit.kind == "text_unit")
    if allowed is not None:
        hits = [hit for hit in hits if str(hit.props.get("document_id") or "") in allowed]
    ids = document_ids_from_hits(hits)[:limit]
    db_ms = (time.perf_counter() - db_started) * 1000
    return FindResult(
        document_ids=tuple(ids),
        strategy="hybrid",
        completeness="partial",
        counters=ops,
        db_ms=db_ms,
        total_ms=(time.perf_counter() - started) * 1000,
    )


def find_category_then_hybrid(
    catalog: Catalog,
    *,
    customer_id: int,
    document_type: str,
    dense_query: Sequence[float],
    limit: int = 50,
    mode: ScopedMode = "scoped_per_document",
    allowed_document_ids: Collection[str] | None = None,
) -> FindResult:
    """Strategy C: category set first, then retrieval constrained to that set.

    Default is per-document scoped search. Integration measurements showed
    scoped_search from the Category node returned no TextUnit hits, while
    scoping from each DocumentVersion recovered the gold set. Prefer measuring
    before switching default to scoped_from_category.
    """
    started = time.perf_counter()
    category = find_by_category(catalog, document_type=document_type)
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
        ids, mode_ops = _hybrid_scoped_from_category(
            catalog,
            customer_id=customer_id,
            document_type=document_type,
            dense_query=dense_query,
            limit=limit,
            allowed=allowed,
        )
    elif mode == "scoped_per_document":
        ids, mode_ops = _hybrid_scoped_per_document(
            catalog,
            customer_id=customer_id,
            dense_query=dense_query,
            limit=limit,
            allowed=allowed,
        )
    else:
        ids, mode_ops = _hybrid_global_post_filter(
            catalog,
            customer_id=customer_id,
            dense_query=dense_query,
            limit=limit,
            allowed=allowed,
        )
    ops = ops.add(mode_ops)
    db_ms = category.db_ms + (time.perf_counter() - db_started) * 1000
    return FindResult(
        document_ids=tuple(ids),
        strategy="category_hybrid",
        completeness="partial",
        counters=ops,
        db_ms=db_ms,
        total_ms=(time.perf_counter() - started) * 1000,
        notes=(mode,),
    )


def find_by_shared_party(
    catalog: Catalog,
    *,
    seed_document_id: str,
    party_name: str,
    customer_id: int,
) -> FindResult:
    """Strategy D: entity + SUBJECT/OBJECT edges → related document_ids."""
    started = time.perf_counter()
    ops = OpCounters()
    db_started = time.perf_counter()
    entity = upsert_entity(
        catalog,
        NodeInput(node_type="core.party", name=party_name, scope=customer_scope(customer_id)),
    )
    ops.neighbor_lookups += 1
    related = _documents_linked_to_entity(catalog, entity.engine_id, ops)
    related.discard(seed_document_id)
    seed = catalog.get_by_key(CANONICAL_DOCUMENT, seed_document_id)
    if seed is not None:
        for peer in seed.props.get("same_party_document_ids") or []:
            related.add(str(peer))
    ids = sorted(related)
    db_ms = (time.perf_counter() - db_started) * 1000
    return FindResult(
        document_ids=tuple(ids),
        strategy="relation",
        completeness="complete" if ids else "partial",
        counters=ops,
        db_ms=db_ms,
        total_ms=(time.perf_counter() - started) * 1000,
    )


def find_within_documents(
    catalog: Catalog,
    *,
    customer_id: int,
    document_ids: Sequence[str],
    dense_query: Sequence[float],
    limit: int = 50,
    allowed_document_ids: Collection[str] | None = None,
) -> FindResult:
    """Hybrid retrieval scoped to an explicit document set (follow-up filter)."""
    started = time.perf_counter()
    allowed = {doc for doc in document_ids if doc}
    if allowed_document_ids is not None:
        allowed &= set(allowed_document_ids)
    if not allowed:
        return FindResult(
            document_ids=(),
            strategy="hybrid",
            completeness="complete",
            counters=OpCounters(),
            db_ms=0.0,
            total_ms=(time.perf_counter() - started) * 1000,
            notes=("within_set", "empty_set"),
        )
    db_started = time.perf_counter()
    ids, ops = _hybrid_scoped_per_document(
        catalog,
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


def filter_to_set(result: FindResult, allowed: Sequence[str]) -> FindResult:
    allowed_set = set(allowed)
    kept = tuple(doc for doc in result.document_ids if doc in allowed_set)
    return FindResult(
        document_ids=kept,
        strategy=result.strategy,
        completeness=result.completeness,
        counters=result.counters,
        db_ms=result.db_ms,
        total_ms=result.total_ms,
        notes=(*result.notes, "within_set"),
    )


def extend_set(current: Sequence[str], added: Sequence[str]) -> list[str]:
    return dedupe_document_ids([*current, *added])


def _hybrid_scoped_from_category(
    catalog: Catalog,
    *,
    customer_id: int,
    document_type: str,
    dense_query: Sequence[float],
    limit: int,
    allowed: set[str],
) -> tuple[list[str], OpCounters]:
    ops = OpCounters()
    cat = catalog.get_by_key(DOCUMENT_CATEGORY, category_key_for_type(document_type))
    if cat is None or cat.engine_id is None:
        return [], ops
    ops.vector_searches += 1
    hits = scoped_search(
        catalog,
        customer_id=customer_id,
        start_key=cat.key,
        start_label=DOCUMENT_CATEGORY,
        dense_query=dense_query,
        max_depth=4,
        limit=limit,
    )
    ops.text_unit_reads += sum(1 for hit in hits if hit.kind == "text_unit")
    ids = [doc for doc in document_ids_from_hits(hits) if doc in allowed]
    return ids, ops


def _hybrid_scoped_per_document(
    catalog: Catalog,
    *,
    customer_id: int,
    dense_query: Sequence[float],
    limit: int,
    allowed: set[str],
) -> tuple[list[str], OpCounters]:
    ops = OpCounters()
    per_doc = max(1, limit // max(1, len(allowed)))
    scored: dict[str, float] = {}
    for document_id in sorted(allowed):
        version_key = _current_version_key(catalog, document_id)
        if version_key is None:
            continue
        ops.vector_searches += 1
        hits = scoped_search(
            catalog,
            customer_id=customer_id,
            start_key=version_key,
            start_label=DOCUMENT_VERSION,
            dense_query=dense_query,
            max_depth=2,
            limit=per_doc,
        )
        ops.text_unit_reads += sum(1 for hit in hits if hit.kind == "text_unit")
        for hit in hits:
            doc = str(hit.props.get("document_id") or "")
            if doc in allowed:
                scored[doc] = max(scored.get(doc, 0.0), hit.score)
    ordered = sorted(scored, key=lambda key: scored[key], reverse=True)[:limit]
    return ordered, ops


def _hybrid_global_post_filter(
    catalog: Catalog,
    *,
    customer_id: int,
    dense_query: Sequence[float],
    limit: int,
    allowed: set[str],
) -> tuple[list[str], OpCounters]:
    """Control arm: global top-K then filter. Expected weaker recall@K."""
    ops = OpCounters()
    ops.vector_searches += 1
    hits = hybrid_search(
        catalog, customer_id=customer_id, dense_query=dense_query, limit=limit,
    )
    ops.text_unit_reads += sum(1 for hit in hits if hit.kind == "text_unit")
    ids = [doc for doc in document_ids_from_hits(hits) if doc in allowed]
    return ids, ops


def _documents_linked_to_entity(
    catalog: Catalog, engine_id: int | None, ops: OpCounters,
) -> set[str]:
    related: set[str] = set()
    if engine_id is None:
        return related
    for direction in ("incoming", "outgoing"):
        for edge_label in (SUBJECT, OBJECT):
            neighbor_ids = catalog.neighbors(
                engine_id, direction=direction, edge_label_filter=[edge_label],
            )
            ops.neighbor_lookups += 1
            for neighbor_id in neighbor_ids:
                row = catalog.get(neighbor_id)
                if row is None:
                    continue
                document_id = str(row.props.get("document_id") or "")
                if document_id:
                    related.add(document_id)
    return related


def _current_version_key(catalog: Catalog, document_id: str) -> str | None:
    document = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    if document is None or document.engine_id is None:
        return None
    for version_engine in catalog.neighbors(
        document.engine_id, direction="outgoing", edge_label_filter=[HAS_VERSION],
    ):
        row = catalog.get(version_engine)
        if row is not None and DOCUMENT_VERSION in row.labels:
            return row.key
    return None
