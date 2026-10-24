"""Bounded read protocol for the single-writer owner.

Every operation is typed by its request ``type``, limited in rows, and returns
node ids/keys with a stable node-id cursor where pagination is needed. The owner
never exposes arbitrary query languages or full-graph dumps.
"""

from __future__ import annotations

from typing import Any

from app.services.overgraph.catalogs import Catalog


def node_payload(row: Any, *, include_vectors: bool) -> dict[str, Any]:
    payload = {
        "id": row.engine_id,
        "key": row.key,
        "labels": list(row.labels),
        "props": dict(row.props),
    }
    if include_vectors and row.dense_vector is not None:
        payload["dense_vector"] = list(row.dense_vector)
    return payload


def _list_nodes(payload: dict[str, Any], catalog: Catalog, catalog_id: str) -> dict[str, Any]:
    label = str(payload["label"])
    filters = dict(payload.get("props") or {})
    limit = max(1, min(int(payload.get("limit", 500)), 1000))
    rows: list[dict[str, Any]] = []
    after: int | None = None
    while len(rows) < limit:
        page, after = catalog.query_nodes(
            label_filter={"labels": [label], "mode": "all"},
            limit=min(limit - len(rows), 500), after=after,
        )
        for row in page:
            props = dict(row.props)
            if any(props.get(name) != value for name, value in filters.items()):
                continue
            rows.append(node_payload(row, include_vectors=bool(payload.get("include_vectors"))))
        if after is None or not page:
            break
    return {"ok": True, "nodes": rows, "catalog_id": catalog_id}


def _read(payload: dict[str, Any], catalog: Catalog) -> dict[str, Any]:
    values: dict[str, Any] = {}
    vectors: dict[str, Any] = {}
    for item in payload.get("keys", []):
        row = catalog.get_by_key(str(item["label"]), str(item["key"]))
        name = f"{item['label']}:{item['key']}"
        values[name] = None if row is None else dict(row.props)
        if payload.get("include_vectors") and row is not None and row.dense_vector is not None:
            vectors[name] = list(row.dense_vector)
    result: dict[str, Any] = {"ok": True, "values": values}
    if payload.get("include_vectors"):
        result["vectors"] = vectors
    return result


def _query_nodes(payload: dict[str, Any], catalog: Catalog, catalog_id: str) -> dict[str, Any]:
    label = str(payload["label"])
    props = dict(payload.get("props") or {})
    limit = max(1, min(int(payload.get("limit", 100)), 1000))
    after = payload.get("after")
    page, next_cursor = catalog.query_nodes(
        label_filter={"labels": [label], "mode": "all"},
        limit=limit, after=int(after) if after is not None else None,
    )
    nodes = [
        node_payload(row, include_vectors=bool(payload.get("include_vectors")))
        for row in page
        if all(row.props.get(name) == value for name, value in props.items())
    ]
    return {
        "ok": True, "nodes": nodes, "next_cursor": next_cursor,
        "catalog_id": catalog_id,
    }


def _node(payload: dict[str, Any], catalog: Catalog) -> dict[str, Any]:
    row = catalog.get(int(payload["node_id"]))
    if row is None:
        return {"ok": True, "node": None}
    limit = max(1, min(int(payload.get("edge_limit", 40)), 200))
    node = node_payload(row, include_vectors=True)
    node["edges"] = catalog.neighbor_edges(
        int(payload["node_id"]), direction="outgoing", limit=limit,
    ) + catalog.neighbor_edges(int(payload["node_id"]), direction="incoming", limit=limit)
    return {"ok": True, "node": node}


def _neighbors(payload: dict[str, Any], catalog: Catalog) -> dict[str, Any]:
    direction = str(payload.get("direction") or "outgoing")
    labels = payload.get("labels") or None
    limit = max(1, min(int(payload.get("limit", 50)), 200))
    rows = catalog.neighbor_edges(
        int(payload["node_id"]), direction=direction,
        edge_label_filter=[str(label) for label in labels] if labels else None,
        limit=limit,
    )
    return {"ok": True, "nodes": rows}


def _count_nodes(payload: dict[str, Any], catalog: Catalog, catalog_id: str) -> dict[str, Any]:
    count = catalog.count_nodes_by_labels([str(payload["label"])])
    return {"ok": True, "count": int(count), "catalog_id": catalog_id}


def _read_handler(payload: dict[str, Any], catalog: Catalog, catalog_id: str) -> dict[str, Any]:
    return _read(payload, catalog)


def _node_handler(payload: dict[str, Any], catalog: Catalog, catalog_id: str) -> dict[str, Any]:
    return _node(payload, catalog)


def _neighbors_handler(
    payload: dict[str, Any], catalog: Catalog, catalog_id: str,
) -> dict[str, Any]:
    return _neighbors(payload, catalog)


READ_HANDLERS = {
    "list_nodes": _list_nodes,
    "read": _read_handler,
    "query_nodes": _query_nodes,
    "count_nodes": _count_nodes,
    "node": _node_handler,
    "neighbors": _neighbors_handler,
}


def handle_read(payload: dict[str, Any], catalog: Catalog, catalog_id: str) -> dict[str, Any] | None:
    handler = READ_HANDLERS.get(str(payload.get("type") or ""))
    if handler is None:
        return None
    if payload.get("catalog_id") != catalog_id:
        return {"ok": False, "error": "catalog_mismatch"}
    return handler(payload, catalog, catalog_id)
