"""Read-only pages of an OverGraph catalog for the admin viewer."""

from __future__ import annotations

import json
from typing import Any

from app.services.overgraph.catalogs import Catalog

OPEN_ENDED = 2**63 - 1
PREVIEW_KEYS = ("text", "name", "content", "memory", "title", "data")
SKIPPED_PROPS = {"dense_vector", "sparse_vector"}
MAX_PROP_CHARS = 4000
PREVIEW_CHARS = 180
PAGE_SIZE = 100
SCAN_CAP = 2000
EDGE_LIMIT = 40


def catalog_summary(catalog: Catalog) -> dict[str, Any]:
    return catalog.read(lambda db: _summary(db, catalog))


def list_nodes(
    catalog: Catalog, *, label: str, query: str, limit: int, after: int | None,
) -> dict[str, Any]:
    needle = query.casefold().strip()
    if needle:
        return catalog.read(lambda db: _scan(db, label=label, needle=needle, limit=limit, after=after))
    return catalog.read(lambda db: _page(db, label, limit, after))


def node_detail(catalog: Catalog, node_id: int) -> dict[str, Any] | None:
    return catalog.read(lambda db: _detail(db, node_id))


def _summary(db: Any, catalog: Catalog) -> dict[str, Any]:
    node_labels = [
        {"label": info.label, "count": int(db.count_nodes_by_labels([info.label]))}
        for info in db.list_node_labels()
    ]
    edge_labels = [
        {"label": info.label, "count": int(db.count_edges_by_label(info.label))}
        for info in db.list_edge_labels()
    ]
    node_labels.sort(key=lambda row: (-row["count"], row["label"]))
    edge_labels.sort(key=lambda row: (-row["count"], row["label"]))
    return {
        "kind": catalog.kind,
        "dimension": catalog.dimension,
        "node_labels": node_labels,
        "edge_labels": edge_labels,
    }


def _page(db: Any, label: str, limit: int, after: int | None) -> dict[str, Any]:
    page = db.get_nodes_by_labels_paged([label], limit=limit, after=after)
    return {
        "nodes": [_node_summary(item) for item in page.items],
        "next_cursor": int(page.next_cursor) if page.next_cursor is not None else None,
    }


def _scan(db: Any, *, label: str, needle: str, limit: int, after: int | None) -> dict[str, Any]:
    found: list[dict[str, Any]] = []
    cursor = after
    scanned = 0
    while scanned < SCAN_CAP and len(found) < limit:
        page = db.get_nodes_by_labels_paged([label], limit=PAGE_SIZE, after=cursor)
        batch = list(page.items)
        if not batch:
            return {"nodes": found, "next_cursor": None}
        for index, item in enumerate(batch):
            scanned += 1
            cursor = int(item.id)
            if _matches(item, needle):
                found.append(_node_summary(item))
            if len(found) >= limit or scanned >= SCAN_CAP:
                more = index < len(batch) - 1 or page.next_cursor is not None
                return {"nodes": found, "next_cursor": cursor if more else None}
        if page.next_cursor is None:
            return {"nodes": found, "next_cursor": None}
        cursor = page.next_cursor
    return {"nodes": found, "next_cursor": cursor}


def _detail(db: Any, node_id: int) -> dict[str, Any] | None:
    view = db.get_node(node_id)
    if view is None:
        return None
    node = _node_summary(view)
    node["props"] = _props(view.props)
    node["created_at"] = _time(view.created_at)
    node["updated_at"] = _time(view.updated_at)
    node["edges"] = _edges(db, node_id, "outgoing") + _edges(db, node_id, "incoming")
    return node


def _edges(db: Any, node_id: int, direction: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in db.neighbors(node_id, direction=direction, limit=EDGE_LIMIT):
        other = db.get_node(entry.node_id)
        edge = db.get_edge(entry.edge_id)
        rows.append({
            "direction": direction,
            "edge_id": int(entry.edge_id),
            "label": str(entry.label),
            "weight": float(entry.weight),
            "valid_from": _time(entry.valid_from),
            "valid_to": _open_time(entry.valid_to),
            "props": _props(getattr(edge, "props", {})),
            "node": _node_summary(other) if other is not None else None,
        })
    return rows


def _node_summary(view: Any) -> dict[str, Any]:
    props = view.props if isinstance(view.props, dict) else {}
    return {
        "id": int(view.id),
        "key": str(view.key),
        "labels": [str(label) for label in view.labels],
        "weight": float(view.weight),
        "preview": _preview(props, str(view.key)),
    }


def _matches(view: Any, needle: str) -> bool:
    if needle in str(view.key).casefold():
        return True
    props = view.props if isinstance(view.props, dict) else {}
    return any(isinstance(value, str) and needle in value.casefold() for value in props.values())


def _preview(props: dict[str, Any], key: str) -> str:
    sources = [_payload(props), props]
    for source in sources:
        if source is None:
            continue
        for name in PREVIEW_KEYS:
            text = _one_line(source.get(name))
            if text:
                return text
    for value in props.values():
        text = _one_line(value)
        if text:
            return text
    return key


def _one_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if not text:
        return ""
    if len(text) <= PREVIEW_CHARS:
        return text
    return text[:PREVIEW_CHARS] + "…"


def _props(value: object) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, dict) else {}
    payload = _payload(raw)
    if payload is not None:
        raw["payload_json"] = payload
    return {
        str(key): _jsonish(item, 1)
        for key, item in list(raw.items())[:80]
        if str(key) not in SKIPPED_PROPS
    }


def _payload(props: dict[str, Any]) -> dict[str, Any] | None:
    raw = props.get("payload_json")
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _jsonish(value: object, depth: int) -> Any:
    if depth > 6:
        return None
    if isinstance(value, str):
        return _clip(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, list):
        return _json_list(value, depth)
    if isinstance(value, dict):
        return _json_dict(value, depth)
    return _clip(str(value))


def _clip(value: str) -> str:
    if len(value) <= MAX_PROP_CHARS:
        return value
    return value[:MAX_PROP_CHARS] + "…"


def _json_list(value: list[object], depth: int) -> Any:
    if _numeric_vector(value):
        return f"[{len(value)} values]"
    return [_jsonish(item, depth + 1) for item in value[:40]]


def _json_dict(value: dict[object, object], depth: int) -> dict[str, Any]:
    return {
        str(key): _jsonish(item, depth + 1)
        for key, item in list(value.items())[:80]
        if str(key) not in SKIPPED_PROPS
    }


def _numeric_vector(value: list[object]) -> bool:
    if len(value) <= 16:
        return False
    return all(isinstance(item, int | float) and not isinstance(item, bool) for item in value)


def _time(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _open_time(value: object) -> int | None:
    if not isinstance(value, int) or value >= OPEN_ENDED:
        return None
    return value
