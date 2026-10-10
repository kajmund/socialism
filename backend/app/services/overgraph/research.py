"""Research reads and writes the knowledge catalog. Documents stay in Postgres."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.graph_v2.identity import namespaced, normalized, stable_id
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog, require_knowledge
from app.services.overgraph.isolation import can_reference, is_visible
from app.services.overgraph.labels import (
    DEPENDS_ON,
    ENTITY,
    FACT,
    IDENTIFIER,
    OBJECT,
    SUBJECT,
    TEXT_UNIT,
    visible_scope_keys,
)
from app.services.overgraph.model import GraphFactView, GraphRecord, TextUnitView, TextUnitWrite
from app.services.overgraph.retrieval import hybrid_search
from app.services.overgraph.write import upsert_entity, upsert_text_unit, write_fact

QUESTION_TYPE = "core.question"
QUESTION_NS = "research.question_id"
INDEX_PREFIX = "research-index:"


@dataclass(frozen=True)
class ResearchFactHit:
    fact: GraphFactView
    score: float
    hop: int = 0


@dataclass(frozen=True)
class ResearchFactWrite:
    fact_id: str
    scope: KnowledgeTenantScope
    source: NodeInput
    target: NodeInput
    predicate: str
    fact_text: str
    unit: TextUnitWrite
    embedding: tuple[float, ...] | None = None
    attributes: dict[str, object] = field(default_factory=dict)
    source_key: str | None = None
    target_key: str | None = None


def _dt(ms: object) -> datetime | None:
    value = int(ms or 0)
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _json_dict(raw: object) -> dict[str, object]:
    if not raw:
        return {}
    parsed = json.loads(str(raw))
    return dict(parsed) if isinstance(parsed, dict) else {}


def _scope_customer(scope_key: str) -> int | None:
    if scope_key == "shared" or ":" not in scope_key:
        return None
    return int(scope_key.split(":", 1)[1])


def _text_unit_refs(props: dict[str, object]) -> tuple[str, ...]:
    parsed = json.loads(str(props.get("source_refs_json") or "[]"))
    return tuple(
        str(item["ref"]) for item in parsed if item.get("kind") == "text_unit" and item.get("ref")
    )


def fact_view(row: GraphRecord) -> GraphFactView:
    props = row.props
    scope_key = str(props.get("scope_key") or "")
    context = str(props.get("context_key") or "")
    return GraphFactView(
        id=row.key,
        scope_key=scope_key,
        customer_id=_scope_customer(scope_key),
        source_id=str(props.get("source_key") or ""),
        target_id=str(props.get("target_key") or ""),
        context_id=context or None,
        predicate=str(props.get("predicate") or ""),
        fact_text=str(props.get("fact_text") or ""),
        status=str(props.get("status") or ""),
        valid_at=_dt(props.get("valid_at_ms")),
        invalid_at=_dt(props.get("invalid_at_ms")),
        attributes=_json_dict(props.get("attributes_json")),
        text_unit_refs=_text_unit_refs(props),
    )


def text_unit_view(row: GraphRecord) -> TextUnitView:
    props = row.props
    scope_key = str(props.get("scope_key") or "")
    locator = str(props.get("locator") or "")
    page_start = int(props.get("page_start") or -1)
    page_end = int(props.get("page_end") or -1)
    return TextUnitView(
        id=row.key,
        document_id=str(props.get("document_id") or ""),
        document_version_id=str(props.get("document_version_id") or ""),
        scope_key=scope_key,
        scope_type="shared" if scope_key == "shared" else "customer",
        customer_id=_scope_customer(scope_key),
        text=str(props.get("text") or ""),
        content_hash=str(props.get("content_hash") or ""),
        ordinal=int(props.get("ordinal") or 0),
        locator=locator or None,
        page_start=None if page_start < 0 else page_start,
        page_end=None if page_end < 0 else page_end,
        valid_from=_dt(props.get("valid_from_ms")),
        valid_to=_dt(props.get("valid_to_ms")),
        extra=_json_dict(props.get("extra_json")),
    )


def mark_scope_index(catalog: Catalog, scope_key: str) -> None:
    catalog.upsert_node(
        [ENTITY, f"scope.{scope_key.replace(':', '.')}"],
        f"{INDEX_PREFIX}{scope_key}",
        props={
            "scope_key": scope_key,
            "node_type": "research.index",
            "name": "index",
            "has_text_unit_facts": 1,
        },
    )


def drop_scope_index(catalog: Catalog, scope_key: str) -> None:
    row = catalog.get_by_key(ENTITY, f"{INDEX_PREFIX}{scope_key}")
    if row is not None and row.engine_id is not None:
        catalog.delete_node(row.engine_id)


def has_supported_facts(catalog: Catalog, customer_id: int | None) -> bool:
    for scope_key in visible_scope_keys(customer_id):
        row = catalog.get_by_key(ENTITY, f"{INDEX_PREFIX}{scope_key}")
        if row is not None and row.props.get("has_text_unit_facts"):
            return True
    return False


def load_fact(catalog: Catalog, fact_id: str, customer_id: int | None) -> GraphFactView | None:
    row = catalog.get_by_key(FACT, fact_id)
    if row is None or not is_visible(str(row.props.get("scope_key") or ""), customer_id):
        return None
    return fact_view(row)


def load_text_units(catalog: Catalog, unit_ids: list[str]) -> list[TextUnitView | None]:
    return [
        text_unit_view(row) if (row := catalog.get_by_key(TEXT_UNIT, identity)) is not None else None
        for identity in unit_ids
    ]


def supporting_units(catalog: Catalog, fact: GraphFactView) -> list[TextUnitView | None]:
    return load_text_units(catalog, list(fact.text_unit_refs))


def _visible_fact(catalog: Catalog, engine_id: int, customer_id: int | None) -> GraphFactView | None:
    row = catalog.get(engine_id)
    if row is None or FACT not in row.labels:
        return None
    if not is_visible(str(row.props.get("scope_key") or ""), customer_id):
        return None
    if row.props.get("status") != "active":
        return None
    return fact_view(row)


def _facts_from_unit(catalog: Catalog, key: str, customer_id: int | None) -> list[GraphFactView]:
    unit = catalog.get_by_key(TEXT_UNIT, key)
    if unit is None or unit.engine_id is None:
        return []
    facts: list[GraphFactView] = []
    for engine_id in catalog.neighbors(unit.engine_id, direction="outgoing"):
        view = _visible_fact(catalog, engine_id, customer_id)
        if view is not None:
            facts.append(view)
    return facts


def search_research_facts(
    catalog: Catalog,
    customer_id: int | None,
    dense_query: list[float],
    limit: int,
) -> list[ResearchFactHit]:
    unique: dict[str, ResearchFactHit] = {}
    for hit in hybrid_search(
        catalog, customer_id=customer_id, dense_query=dense_query, limit=limit,
    ):
        if hit.kind == "fact":
            row = catalog.get_by_key(FACT, hit.key)
            if row is None or row.props.get("status") != "active":
                continue
            unique.setdefault(hit.key, ResearchFactHit(fact_view(row), hit.score, hit.hop))
            continue
        if hit.kind != "text_unit":
            continue
        for fact in _facts_from_unit(catalog, hit.key, customer_id):
            unique.setdefault(fact.id, ResearchFactHit(fact, hit.score, hit.hop))
    return list(unique.values())[:limit]


def neighbourhood_facts(
    catalog: Catalog,
    customer_id: int | None,
    seeds: list[str],
    limit: int,
) -> list[ResearchFactHit]:
    unique: dict[str, ResearchFactHit] = {}
    for seed in seeds:
        entity = catalog.get_by_key(ENTITY, seed)
        if entity is None or entity.engine_id is None:
            continue
        if not is_visible(str(entity.props.get("scope_key") or ""), customer_id):
            continue
        for engine_id in catalog.neighbors(
            entity.engine_id, direction="incoming", edge_label_filter=[SUBJECT, OBJECT],
        ):
            view = _visible_fact(catalog, engine_id, customer_id)
            if view is not None:
                unique.setdefault(view.id, ResearchFactHit(view, 1.0, 1))
            if len(unique) >= limit:
                return list(unique.values())
    return list(unique.values())


def _question_alias(scope_key: str, question_id: str) -> str:
    return stable_id(scope_key, namespaced(QUESTION_NS), normalized(question_id))


def find_question(
    catalog: Catalog, question_id: str, customer_id: int | None,
) -> GraphRecord | None:
    for scope_key in visible_scope_keys(customer_id):
        ident = catalog.get_by_key(IDENTIFIER, _question_alias(scope_key, question_id))
        if ident is None:
            continue
        node_key = str(ident.props.get("node_key") or "")
        row = catalog.get_by_key(ENTITY, node_key)
        if row is None:
            continue
        if is_visible(str(row.props.get("scope_key") or ""), customer_id):
            return row
    return None


def question_facts(
    catalog: Catalog, question_id: str, customer_id: int | None, limit: int,
) -> list[ResearchFactHit]:
    question = find_question(catalog, question_id, customer_id)
    if question is None or question.engine_id is None:
        return []
    hits: list[ResearchFactHit] = []
    for engine_id in catalog.neighbors(
        question.engine_id, direction="outgoing", edge_label_filter=[DEPENDS_ON],
    ):
        view = _visible_fact(catalog, engine_id, customer_id)
        if view is not None:
            hits.append(ResearchFactHit(view, 1.0, 0))
        if len(hits) >= limit:
            break
    return hits


def attach_question_dependency(
    catalog: Catalog,
    *,
    question_id: str,
    question_text: str,
    fact_id: str,
    scope: KnowledgeTenantScope,
) -> None:
    question = upsert_entity(catalog, NodeInput(
        node_type=QUESTION_TYPE,
        name=question_text,
        scope=scope,
        identifier_namespace=QUESTION_NS,
        identifier=question_id,
        attributes={"canonical_question_id": question_id},
    ))
    fact = catalog.get_by_key(FACT, fact_id)
    if fact is None or fact.engine_id is None or question.engine_id is None:
        raise RuntimeError(f"cannot attach question {question_id} to missing fact {fact_id}")
    catalog.upsert_edge(question.engine_id, fact.engine_id, DEPENDS_ON)


def _entity_key(catalog: Catalog, proposed: NodeInput, key: str | None) -> str:
    row = upsert_entity(catalog, proposed)
    if key is None or key == row.key:
        return row.key
    catalog.upsert_node(list(row.labels), key, props=dict(row.props))
    return key


def persist_research_fact(catalog: Catalog, proposed: ResearchFactWrite) -> GraphFactView:
    source_key = _entity_key(catalog, proposed.source, proposed.source_key)
    target_key = _entity_key(catalog, proposed.target, proposed.target_key)
    upsert_text_unit(catalog, proposed.unit)
    unit_ref = SourceRef("text_unit", proposed.unit.unit_id)
    sources = (
        (unit_ref,)
        if can_reference(proposed.scope, proposed.unit.scope.scope_key)
        else (SourceRef("episode", proposed.fact_id),)
    )
    write_fact(
        catalog,
        FactInput(
            source_id=source_key,
            target_id=target_key,
            scope=proposed.scope,
            predicate=proposed.predicate,
            fact_text=proposed.fact_text,
            sources=sources,
            embedding=proposed.embedding,
            attributes=proposed.attributes,
        ),
        key=proposed.fact_id,
    )
    update_fact(
        catalog, proposed.fact_id,
        source_refs=[{"kind": "text_unit", "ref": proposed.unit.unit_id}],
    )
    mark_scope_index(catalog, proposed.scope.scope_key)
    row = catalog.get_by_key(FACT, proposed.fact_id)
    if row is None:
        raise RuntimeError(f"failed to persist research fact {proposed.fact_id}")
    return fact_view(row)


def update_fact(catalog: Catalog, fact_id: str, **changes: Any) -> GraphFactView:
    row = catalog.get_by_key(FACT, fact_id)
    if row is None:
        raise RuntimeError(f"missing fact {fact_id}")
    props = dict(row.props)
    if "status" in changes:
        props["status"] = changes["status"]
    if "valid_at" in changes:
        value = changes["valid_at"]
        props["valid_at_ms"] = int(value.timestamp() * 1000) if value is not None else 0
    if "invalid_at" in changes:
        value = changes["invalid_at"]
        props["invalid_at_ms"] = int(value.timestamp() * 1000) if value is not None else 0
    if "attributes" in changes:
        props["attributes_json"] = json.dumps(
            changes["attributes"], ensure_ascii=False, sort_keys=True,
        )
    if "source_refs" in changes:
        props["source_refs_json"] = json.dumps(changes["source_refs"], ensure_ascii=False)
    catalog.upsert_node(list(row.labels), fact_id, props=props, dense_vector=row.dense_vector)
    updated = catalog.get_by_key(FACT, fact_id)
    if updated is None:
        raise RuntimeError(f"failed to update fact {fact_id}")
    return fact_view(updated)


def add_text_unit_ref(catalog: Catalog, fact_id: str, unit_id: str) -> GraphFactView:
    row = catalog.get_by_key(FACT, fact_id)
    if row is None:
        raise RuntimeError(f"missing fact {fact_id}")
    refs = json.loads(str(row.props.get("source_refs_json") or "[]"))
    refs.append({"kind": "text_unit", "ref": unit_id})
    return update_fact(catalog, fact_id, source_refs=refs)


def set_text_unit_refs(catalog: Catalog, fact_id: str, unit_ids: list[str]) -> GraphFactView:
    return update_fact(
        catalog, fact_id,
        source_refs=[{"kind": "text_unit", "ref": unit_id} for unit_id in unit_ids],
    )


def collect_research_hits(
    catalog: Catalog,
    *,
    customer_id: int | None,
    question_id: str | None,
    dense_query: list[float],
    bound: int,
) -> list[ResearchFactHit]:
    direct = question_facts(catalog, question_id, customer_id, bound) if question_id else []
    hybrid = search_research_facts(catalog, customer_id, dense_query, bound)
    seeds = list(
        dict.fromkeys(
            node for hit in [*direct, *hybrid] for node in (hit.fact.source_id, hit.fact.target_id)
        )
    )
    expanded = neighbourhood_facts(catalog, customer_id, seeds, bound) if seeds else []
    unique: dict[str, ResearchFactHit] = {}
    for hit in [*direct, *hybrid, *expanded]:
        unique.setdefault(hit.fact.id, hit)
    return list(unique.values())


def question_seed_keys(
    catalog: Catalog, customer_id: int, facts: list[GraphFactView], limit: int,
) -> list[str]:
    keys: list[str] = []
    for fact in facts:
        for endpoint in (fact.source_id, fact.target_id):
            row = catalog.get_by_key(ENTITY, endpoint)
            if row is not None and row.props.get("node_type") == QUESTION_TYPE:
                keys.append(endpoint)
        stored = catalog.get_by_key(FACT, fact.id)
        if stored is None or stored.engine_id is None:
            continue
        for engine_id in catalog.neighbors(
            stored.engine_id, direction="incoming", edge_label_filter=[DEPENDS_ON],
        ):
            question = catalog.get(engine_id)
            if question is not None and is_visible(
                str(question.props.get("scope_key") or ""), customer_id,
            ):
                keys.append(question.key)
    return list(dict.fromkeys(keys))[:limit]


def question_frontier(
    catalog: Catalog,
    *,
    customer_id: int,
    frontier: list[str],
    visited: set[str],
    remaining: int,
    predicates: tuple[str, ...],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen = set(visited)
    for start in frontier:
        entity = catalog.get_by_key(ENTITY, start)
        if entity is None or entity.engine_id is None:
            continue
        for engine_id in catalog.neighbors(
            entity.engine_id, direction="incoming", edge_label_filter=[SUBJECT, OBJECT],
        ):
            view = _visible_fact(catalog, engine_id, customer_id)
            if view is None or view.id in seen or view.predicate not in predicates:
                continue
            source = catalog.get_by_key(ENTITY, view.source_id)
            target = catalog.get_by_key(ENTITY, view.target_id)
            if source is None or target is None:
                continue
            seen.add(view.id)
            rows.append({
                "id": view.id,
                "predicate": view.predicate,
                "source_id": view.source_id,
                "target_id": view.target_id,
                "source_question": str(source.props.get("name") or ""),
                "target_question": str(target.props.get("name") or ""),
            })
            if len(rows) >= remaining:
                return rows
    return rows


def knowledge_catalog() -> Catalog:
    return require_knowledge()


async def lookup_candidates(
    *,
    customer_id: int | None,
    question_id: str | None,
    dense_query: list[float],
    bound: int,
) -> list[ResearchFactHit]:
    catalog = require_knowledge()

    def work() -> list[ResearchFactHit]:
        return collect_research_hits(
            catalog,
            customer_id=customer_id,
            question_id=question_id,
            dense_query=dense_query,
            bound=bound,
        )

    return await catalog.run(work)


async def graph_has_supported_facts(customer_id: int | None) -> bool:
    catalog = require_knowledge()
    return await catalog.run(has_supported_facts, catalog, customer_id)
