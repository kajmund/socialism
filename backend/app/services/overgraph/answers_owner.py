"""Owner-backed reads for persisted research answers.

The owner owns the knowledge catalog; these functions are the authoritative
lookup path for answer reuse in owner mode. Ranking, scoring and reuse decisions
stay in the research layer.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.services.overgraph.answers import (
    ANSWER_PREDICATE,
    EntityView,
    _question_alias,
)
from app.services.overgraph.isolation import is_visible
from app.services.overgraph.labels import ENTITY, FACT, IDENTIFIER, SUBJECT, visible_scope_keys
from app.services.overgraph.model import GraphFactView, GraphRecord
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.views import fact_view

def _name(label: str, key: str) -> str:
    return f"{label}:{key}"


def _record(key: str, props: dict[str, Any], engine_id: Any, labels: tuple[str, ...] = ()) -> GraphRecord:
    return GraphRecord(
        key=key, labels=labels, props=dict(props),
        engine_id=int(engine_id) if engine_id is not None else None,
    )


async def find_question_via_owner(
    client: OwnerClient, question_id: str, customer_id: int | None,
) -> GraphRecord | None:
    scopes = visible_scope_keys(customer_id)
    aliases = [
        {"label": IDENTIFIER, "key": _question_alias(scope, question_id)}
        for scope in scopes
    ]
    identifiers = await client.read(aliases)
    node_keys: list[str] = []
    for alias in aliases:
        props = identifiers["values"].get(_name(IDENTIFIER, alias["key"])) or {}
        node_key = str(props.get("node_key") or "")
        if node_key:
            node_keys.append(node_key)
    if not node_keys:
        return None
    nodes = await client.read([{"label": ENTITY, "key": key} for key in node_keys])
    for key in node_keys:
        props = nodes["values"].get(_name(ENTITY, key))
        if props is None:
            continue
        if not is_visible(str(props.get("scope_key") or ""), customer_id):
            continue
        return _record(key, props, nodes["ids"].get(_name(ENTITY, key)), (ENTITY,))
    return None


async def answer_facts_via_owner(
    client: OwnerClient, question_id: str, customer_id: int | None, *,
    limit: int = 200, now: datetime | None = None, exact_scope: str | None = None,
) -> list[GraphFactView]:
    """Active answer facts for a canonical question, newest first."""
    question = await find_question_via_owner(client, question_id, customer_id)
    if question is None or question.engine_id is None:
        return []
    edges = await client.neighbors(
        question.engine_id, direction="incoming", labels=[SUBJECT], limit=200,
    )
    rows: list[GraphRecord] = []
    for edge in edges:
        props = dict(edge.get("props") or {})
        if FACT not in {str(label) for label in edge.get("labels") or ()}:
            continue
        if str(props.get("predicate") or "") != ANSWER_PREDICATE:
            continue
        if str(props.get("status") or "") != "active":
            continue
        if exact_scope is not None and str(props.get("scope_key") or "") != exact_scope:
            continue
        if now is not None and not _current_fact_row(props, now):
            continue
        rows.append(_record(
            str(edge.get("key") or ""), props, edge.get("node_id"),
            tuple(str(label) for label in edge.get("labels") or ()),
        ))
    rows.sort(
        key=lambda row: (int(row.props.get("created_at_ms") or 0), row.engine_id or 0),
        reverse=True,
    )
    return [fact_view(row) for row in rows[:limit]]


def _current_fact_row(props: dict[str, Any], now: datetime) -> bool:
    stamp = int(now.timestamp() * 1000)
    valid_at = int(props.get("valid_at_ms") or 0)
    invalid_at = int(props.get("invalid_at_ms") or 0)
    if valid_at and valid_at > stamp:
        return False
    return not invalid_at or stamp < invalid_at


async def entity_attributes_via_owner(
    client: OwnerClient, key: str,
) -> EntityView | None:
    result = await client.read([{"label": ENTITY, "key": key}])
    props = result["values"].get(_name(ENTITY, key))
    if props is None:
        return None
    raw = props.get("attributes_json")
    parsed = json.loads(str(raw)) if raw else {}
    return EntityView(
        scope_key=str(props.get("scope_key") or ""),
        node_type=str(props.get("node_type") or ""),
        name=str(props.get("name") or ""),
        attributes=dict(parsed) if isinstance(parsed, dict) else {},
    )


async def current_fact_via_owner(
    client: OwnerClient, fact_id: str, scope_key: str, now: datetime,
) -> bool:
    result = await client.read([{"label": FACT, "key": fact_id}])
    props = result["values"].get(_name(FACT, fact_id))
    if props is None:
        return False
    return _fact_is_current(props, fact_id, scope_key, now)


async def current_facts_via_owner(
    client: OwnerClient, fact_ids: list[str], scope_key: str, now: datetime,
    *, batch_size: int = 200,
) -> bool:
    if not fact_ids:
        return True
    for start in range(0, len(fact_ids), batch_size):
        batch = fact_ids[start:start + batch_size]
        result = await client.read([{"label": FACT, "key": fact_id} for fact_id in batch])
        for fact_id in batch:
            props = result["values"].get(_name(FACT, fact_id))
            if props is None or not _fact_is_current(props, fact_id, scope_key, now):
                return False
    return True


def _fact_is_current(
    props: dict[str, Any], fact_id: str, scope_key: str, now: datetime,
) -> bool:
    view = fact_view(_record(fact_id, props, None, (FACT,)))
    if view.scope_key not in ("shared", scope_key) or view.status != "active":
        return False
    if view.valid_at is not None and view.valid_at > now:
        return False
    return view.invalid_at is None or now < view.invalid_at
