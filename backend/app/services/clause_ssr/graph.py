"""Shared OverGraph helpers for the clause SSR adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.isolation import assert_visible, can_reference
from app.services.overgraph.labels import scope_label, visible_scope_keys
from app.services.overgraph.model import GraphRecord


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def node_labels(kind: str, scope_key: str) -> list[str]:
    return [kind, scope_label(scope_key)]


def require_node(catalog: Catalog, label: str, key: str) -> GraphRecord:
    row = catalog.get_by_key(label, key)
    if row is None:
        raise KeyError(f"missing graph node {label}:{key}")
    return row


def upsert_scoped(
    catalog: Catalog,
    *,
    kind: str,
    key: str,
    scope: KnowledgeTenantScope,
    props: dict[str, Any],
    dense_vector: list[float] | None = None,
) -> GraphRecord:
    payload = dict(props)
    payload["scope_key"] = scope.scope_key
    catalog.upsert_node(
        node_labels(kind, scope.scope_key),
        key,
        props=payload,
        dense_vector=dense_vector,
    )
    return require_node(catalog, kind, key)


def link(
    catalog: Catalog,
    source: GraphRecord,
    target: GraphRecord,
    *,
    label: str,
    props: dict[str, Any] | None = None,
) -> None:
    if source.engine_id is None or target.engine_id is None:
        raise RuntimeError(f"cannot link {source.key} → {target.key} without engine ids")
    catalog.upsert_edge(source.engine_id, target.engine_id, label, props=props or {})


def find_by_prop(catalog: Catalog, label: str, prop_key: str, prop_value: object) -> list[GraphRecord]:
    rows: list[GraphRecord] = []
    after: int | None = None
    while True:
        page, after = catalog.query_nodes(
            label_filter={"labels": [label], "mode": "all"},
            filter_spec={"property": prop_key, "eq": prop_value},
            limit=500,
            after=after,
        )
        rows.extend(page)
        if after is None or not page:
            break
    return rows


def list_visible(catalog: Catalog, label: str, customer_id: int | None) -> list[GraphRecord]:
    rows: list[GraphRecord] = []
    for scope_key in visible_scope_keys(customer_id):
        rows.extend(_pages(catalog, label, scope_key))
    return rows


def _pages(catalog: Catalog, label: str, scope_key: str) -> list[GraphRecord]:
    rows: list[GraphRecord] = []
    after: int | None = None
    while True:
        page, after = catalog.query_nodes(
            label_filter={"labels": [label, scope_label(scope_key)], "mode": "all"},
            limit=500,
            after=after,
        )
        rows.extend(page)
        if after is None or not page:
            break
    return rows


def prop_str(row: GraphRecord, name: str) -> str:
    return str(row.props.get(name) or "")


def prop_int(row: GraphRecord, name: str, default: int = 0) -> int:
    raw = row.props.get(name)
    return int(raw) if raw is not None and raw != "" else default


def prop_bool(row: GraphRecord, name: str) -> bool:
    raw = row.props.get(name)
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in {"1", "true", "yes"}


def assert_scope_write(owner: KnowledgeTenantScope, target_scope: str) -> None:
    if target_scope != owner.scope_key:
        raise PermissionError(f"cannot write {target_scope} from {owner.scope_key}")


def assert_readable(scope_key: str, customer_id: int | None) -> None:
    assert_visible(scope_key, customer_id)


def assert_can_use(owner: KnowledgeTenantScope, target_scope: str) -> None:
    if not can_reference(owner, target_scope):
        raise PermissionError(f"graph node {target_scope} is outside the caller tenant")
