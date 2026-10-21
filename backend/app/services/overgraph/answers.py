"""Question and answer reads over the knowledge catalog.

``canonical_question_id`` is a stable entry point: the question alias index resolves it
to the question node, and answers hang off that node through ``SUBJECT`` edges. No vector
search and no SQL join is needed to resume a known answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from app.services.graph_v2.identity import namespaced, normalized, stable_id
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.isolation import is_visible
from app.services.overgraph.labels import ENTITY, FACT, IDENTIFIER, SUBJECT, visible_scope_keys
from app.services.overgraph.model import GraphFactView, GraphRecord
from app.services.overgraph.views import fact_view

QUESTION_TYPE = "core.question"
ANSWER_TYPE = "research.answer"
ANSWER_PREDICATE = "research.answered_by"
QUESTION_NS = "research.question_id"


def _question_alias(scope_key: str, question_id: str) -> str:
    return stable_id(scope_key, namespaced(QUESTION_NS), normalized(question_id))


def _question_node(
    catalog: Catalog, scope_key: str, question_id: str,
) -> GraphRecord | None:
    ident = catalog.get_by_key(IDENTIFIER, _question_alias(scope_key, question_id))
    if ident is None:
        return None
    node_key = str(ident.props.get("node_key") or "")
    return catalog.get_by_key(ENTITY, node_key)



def find_question(
    catalog: Catalog, question_id: str, customer_id: int | None,
) -> GraphRecord | None:
    for scope_key in visible_scope_keys(customer_id):
        row = _question_node(catalog, scope_key, question_id)
        if row is None:
            continue
        if is_visible(str(row.props.get("scope_key") or ""), customer_id):
            return row
    return None


def answer_facts(
    catalog: Catalog,
    question_id: str,
    customer_id: int | None,
    *,
    limit: int = 200,
    now: datetime | None = None,
    exact_scope: str | None = None,
) -> list[GraphFactView]:
    """Active answer facts for a canonical question id, newest first.

    ``canonical_question_id`` resolves through the question alias index, so a known
    answer is reachable without a vector search. Answers are found by the ``SUBJECT``
    edge every answer fact has to its question node.

    Status and (when ``now`` is given) the validity window are filtered **before**
    ``limit`` is applied, so historical answers can never push a current answer out.
    """
    rows: list[GraphRecord] = []
    for scope_key in visible_scope_keys(customer_id):
        if exact_scope is not None and scope_key != exact_scope:
            continue
        question = _question_node(catalog, scope_key, question_id)
        if question is None or question.engine_id is None:
            continue
        if not is_visible(str(question.props.get("scope_key") or ""), customer_id):
            continue
        for engine_id in catalog.neighbors(
            question.engine_id, direction="incoming", edge_label_filter=[SUBJECT],
        ):
            row = catalog.get(engine_id)
            if row is None or FACT not in row.labels:
                continue
            if str(row.props.get("predicate") or "") != ANSWER_PREDICATE:
                continue
            if str(row.props.get("status") or "") != "active":
                continue
            if exact_scope is not None and str(row.props.get("scope_key") or "") != exact_scope:
                continue
            if now is not None and not _current_fact_row(row, now):
                continue
            rows.append(row)
    rows.sort(
        key=lambda row: (int(row.props.get("created_at_ms") or 0), row.engine_id or 0),
        reverse=True,
    )
    return [fact_view(row) for row in rows[:limit]]


def _current_fact_row(row: GraphRecord, now: datetime) -> bool:
    valid_at = int(row.props.get("valid_at_ms") or 0)
    invalid_at = int(row.props.get("invalid_at_ms") or 0)
    if valid_at and valid_at > int(now.timestamp() * 1000):
        return False
    return not invalid_at or int(now.timestamp() * 1000) < invalid_at


@dataclass(frozen=True)
class EntityView:
    """An entity node resolved by its stable key."""

    scope_key: str
    node_type: str
    name: str
    attributes: dict[str, object]


def entity_attributes(catalog: Catalog, key: str) -> EntityView | None:
    """Scope key, node type, name and attributes of an entity (indexed lookup)."""
    row = catalog.get_by_key(ENTITY, key)
    if row is None:
        return None
    raw = row.props.get("attributes_json")
    parsed = json.loads(str(raw)) if raw else {}
    attributes = dict(parsed) if isinstance(parsed, dict) else {}
    return EntityView(
        scope_key=str(row.props.get("scope_key") or ""),
        node_type=str(row.props.get("node_type") or ""),
        name=str(row.props.get("name") or ""),
        attributes=attributes,
    )


def current_fact(
    catalog: Catalog, fact_id: str, scope_key: str, now: datetime,
) -> bool:
    """A fact referenced by an answer basis is still current and readable."""
    row = catalog.get_by_key(FACT, fact_id)
    if row is None:
        return False
    view = fact_view(row)
    if view.scope_key not in ("shared", scope_key) or view.status != "active":
        return False
    if view.valid_at is not None and view.valid_at > now:
        return False
    return view.invalid_at is None or now < view.invalid_at



