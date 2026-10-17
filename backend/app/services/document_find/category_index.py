"""Indexed category → document_ids on tenant OverGraph. No TextUnit scans."""

from __future__ import annotations

from app.services.document_find.labels import (
    CANONICAL_DOCUMENT,
    DOCUMENT_CATEGORY,
    IN_CATEGORY,
)
from app.services.document_find.taxonomy import require_type
from app.services.document_find.types import OpCounters
from app.services.overgraph.catalogs import Catalog

TYPE_PREFIX = "type:"


def category_key_for_type(document_type: str) -> str:
    return f"{TYPE_PREFIX}{require_type(document_type)}"


def ensure_document(catalog: Catalog, document_id: str) -> int:
    existing = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    archived = int((existing.props if existing else {}).get("archived") or 0)
    props = dict(existing.props) if existing else {"document_id": document_id, "archived": archived}
    props["document_id"] = document_id
    props["archived"] = archived
    return catalog.upsert_node([CANONICAL_DOCUMENT], document_id, props=props)


def apply_effective_type(
    catalog: Catalog,
    *,
    document_id: str,
    document_type: str,
    counters: OpCounters | None = None,
) -> None:
    """Write effective_type and link the document into the type category index."""
    document_type = require_type(document_type)
    ops = counters or OpCounters()
    document_engine = ensure_document(catalog, document_id)
    row = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    if row is None or row.engine_id is None:
        raise RuntimeError(f"document missing after upsert: {document_id}")
    previous = str((row.props or {}).get("effective_type") or "")
    props = dict(row.props)
    props["effective_type"] = document_type
    props["document_id"] = document_id
    catalog.upsert_node([CANONICAL_DOCUMENT], document_id, props=props)
    if previous and previous != document_type:
        _unlink(catalog, document_id=document_id, document_type=previous, ops=ops)
    cat_key = category_key_for_type(document_type)
    cat_engine = catalog.upsert_node(
        [DOCUMENT_CATEGORY],
        cat_key,
        props={"kind": "type", "value": document_type},
    )
    catalog.upsert_edge(cat_engine, document_engine, IN_CATEGORY)
    ops.neighbor_lookups += 1


def documents_for_type(
    catalog: Catalog,
    document_type: str,
    *,
    counters: OpCounters | None = None,
) -> list[str]:
    """Return every document_id in the type category. No top-K, no TextUnits."""
    ops = counters or OpCounters()
    ops.category_lookups += 1
    cat = catalog.get_by_key(DOCUMENT_CATEGORY, category_key_for_type(document_type))
    if cat is None or cat.engine_id is None:
        return []
    neighbor_ids = catalog.neighbors(
        cat.engine_id, direction="outgoing", edge_label_filter=[IN_CATEGORY],
    )
    ops.neighbor_lookups += 1
    out: list[str] = []
    for engine_id in neighbor_ids:
        row = catalog.get(engine_id)
        if row is None or CANONICAL_DOCUMENT not in row.labels:
            continue
        if int(row.props.get("archived") or 0):
            continue
        document_id = str(row.props.get("document_id") or row.key)
        out.append(document_id)
    return sorted(set(out))


def _unlink(
    catalog: Catalog, *, document_id: str, document_type: str, ops: OpCounters,
) -> None:
    cat = catalog.get_by_key(DOCUMENT_CATEGORY, category_key_for_type(document_type))
    document = catalog.get_by_key(CANONICAL_DOCUMENT, document_id)
    if cat is None or cat.engine_id is None or document is None or document.engine_id is None:
        return
    # OverGraph edge uniqueness is (from, to, label); re-upsert with zero weight is not delete.
    # Leaving a stale edge would keep the document in the old category. Invalidate via graph_patch
    # by deleting the edge if the engine exposes edge ids through neighbors — not available here.
    # Workaround: rebuild category membership by scanning neighbors is avoided; instead we only
    # support reclassification in tests by removing the document from the old category's
    # adjacency through a fresh Category node rebuild for that type when needed.
    _rebuild_category_without(catalog, document_type=document_type, exclude=document_id, ops=ops)


def _rebuild_category_without(
    catalog: Catalog, *, document_type: str, exclude: str, ops: OpCounters,
) -> None:
    current = documents_for_type(catalog, document_type, counters=ops)
    kept = [doc for doc in current if doc != exclude]
    cat_key = category_key_for_type(document_type)
    old = catalog.get_by_key(DOCUMENT_CATEGORY, cat_key)
    if old is not None and old.engine_id is not None:
        catalog.delete_node(old.engine_id)
    cat_engine = catalog.upsert_node(
        [DOCUMENT_CATEGORY],
        cat_key,
        props={"kind": "type", "value": document_type},
    )
    for document_id in kept:
        document_engine = ensure_document(catalog, document_id)
        catalog.upsert_edge(cat_engine, document_engine, IN_CATEGORY)
