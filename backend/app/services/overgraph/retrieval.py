"""OverGraph hybrid, scoped, PPR and neighbour retrieval."""

from collections.abc import Sequence

from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.isolation import is_visible
from app.services.overgraph.labels import (
    CONTAINS,
    CONTEXT,
    FACT,
    NEXT,
    OBJECT,
    SUBJECT,
    SUPPORTS,
    TEXT_UNIT,
)
from app.services.overgraph.model import GraphRecord, KnowledgeHit

TRAVERSAL_EDGES = (SUBJECT, OBJECT, CONTEXT, SUPPORTS, NEXT, CONTAINS)


def _kind(row: GraphRecord) -> str:
    if FACT in row.labels:
        return "fact"
    if TEXT_UNIT in row.labels:
        return "text_unit"
    return "entity"


def _hit(row: GraphRecord, score: float, hop: int = 0) -> KnowledgeHit:
    return KnowledgeHit(
        key=row.key,
        kind=_kind(row),  # type: ignore[arg-type]
        score=score,
        scope_key=str(row.props.get("scope_key") or ""),
        text=str(row.props.get("fact_text") or row.props.get("text") or ""),
        props=row.props,
        hop=hop,
    )


def _visible_row(row: GraphRecord | None, customer_id: int | None) -> GraphRecord | None:
    if row is None or row.engine_id is None:
        return None
    if not is_visible(str(row.props.get("scope_key") or ""), customer_id):
        return None
    return row


def hybrid_search(
    catalog: Catalog,
    *,
    customer_id: int | None,
    dense_query: Sequence[float],
    limit: int = 20,
    sparse_query: Sequence[tuple[int, float]] | None = None,
) -> list[KnowledgeHit]:
    mode = "hybrid" if sparse_query is not None else "dense"
    merged: dict[str, KnowledgeHit] = {}
    for kind in (FACT, TEXT_UNIT):
        for engine_id, score in catalog.scoped_type_search(
            kind=kind, customer_id=customer_id, k=limit,
            dense_query=dense_query, mode=mode, sparse_query=sparse_query,
        ):
            row = _visible_row(catalog.get(engine_id), customer_id)
            if row is None:
                continue
            hit = _hit(row, score)
            previous = merged.get(hit.key)
            if previous is None or hit.score > previous.score:
                merged[hit.key] = hit
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:limit]


def scoped_search(
    catalog: Catalog,
    *,
    customer_id: int | None,
    start_key: str,
    start_label: str,
    dense_query: Sequence[float],
    max_depth: int = 2,
    limit: int = 20,
) -> list[KnowledgeHit]:
    start = catalog.get_by_key(start_label, start_key)
    start = _visible_row(start, customer_id)
    if start is None or start.engine_id is None:
        return []
    hits = catalog.vector_search("dense", {
        "k": limit,
        "dense_query": dense_query,
        "scope_start_node_id": start.engine_id,
        "scope_max_depth": max_depth,
    })
    out: list[KnowledgeHit] = []
    for engine_id, score in hits:
        row = _visible_row(catalog.get(engine_id), customer_id)
        if row is None:
            continue
        out.append(_hit(row, score))
    return out


def rank_seeds(
    catalog: Catalog,
    *,
    customer_id: int | None,
    seeds: Sequence[KnowledgeHit],
    max_results: int = 50,
) -> list[KnowledgeHit]:
    engine_ids: list[int] = []
    for seed in seeds:
        label = FACT if seed.kind == "fact" else TEXT_UNIT
        row = _visible_row(catalog.get_by_key(label, seed.key), customer_id)
        if row is not None and row.engine_id is not None:
            engine_ids.append(row.engine_id)
    if not engine_ids:
        return []
    ranks = catalog.personalized_pagerank(
        engine_ids, algorithm="approx", max_results=max_results,
        edge_label_filter=TRAVERSAL_EDGES,
    )
    out: list[KnowledgeHit] = []
    for engine_id, score in ranks:
        row = _visible_row(catalog.get(engine_id), customer_id)
        if row is None:
            continue
        out.append(_hit(row, score))
    return out


def top_neighbors(
    catalog: Catalog, *, customer_id: int | None, key: str, label: str, k: int = 8,
) -> list[KnowledgeHit]:
    start = _visible_row(catalog.get_by_key(label, key), customer_id)
    if start is None or start.engine_id is None:
        return []
    out: list[KnowledgeHit] = []
    for engine_id, score in catalog.top_k_neighbors(start.engine_id, k):
        row = _visible_row(catalog.get(engine_id), customer_id)
        if row is None:
            continue
        out.append(_hit(row, score, hop=1))
    return out


def bounded_traverse(
    catalog: Catalog, *, customer_id: int | None, key: str, label: str, max_depth: int = 3,
) -> list[KnowledgeHit]:
    start = _visible_row(catalog.get_by_key(label, key), customer_id)
    if start is None or start.engine_id is None:
        return []
    out: list[KnowledgeHit] = []
    for engine_id, depth in catalog.traverse(start.engine_id, max_depth):
        row = _visible_row(catalog.get(engine_id), customer_id)
        if row is None:
            continue
        out.append(_hit(row, 1 / max(depth, 1), hop=depth))
    return out
