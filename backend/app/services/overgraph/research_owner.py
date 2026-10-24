"""Owner-backed reads for graph reuse and hybrid/vector retrieval.

Search itself (vector scoring, per-scope top-k merge, ordering) runs in the
owner; the backend only hydrates the bounded candidate list and applies the
existing research filters/ranking unchanged.
"""

from __future__ import annotations

from typing import Any

from app.services.overgraph.answers_owner import find_question_via_owner
from app.services.overgraph.isolation import is_visible
from app.services.overgraph.labels import (
    DEPENDS_ON,
    ENTITY,
    FACT,
    OBJECT,
    SUBJECT,
    TEXT_UNIT,
    visible_scope_keys,
)
from app.services.overgraph.model import GraphFactView, GraphRecord
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.research import INDEX_PREFIX, ResearchFactHit
from app.services.overgraph.views import fact_view, text_unit_view


def _record(key: str, props: dict[str, Any], engine_id: Any, labels: tuple[str, ...]) -> GraphRecord:
    return GraphRecord(
        key=key, labels=labels, props=dict(props),
        engine_id=int(engine_id) if engine_id is not None else None,
    )


def _visible_fact(edge: dict[str, Any], customer_id: int | None) -> GraphFactView | None:
    props = dict(edge.get("props") or {})
    if FACT not in {str(label) for label in edge.get("labels") or ()}:
        return None
    if not is_visible(str(props.get("scope_key") or ""), customer_id):
        return None
    if str(props.get("status") or "") != "active":
        return None
    return fact_view(_record(str(edge.get("key") or ""), props, edge.get("node_id"), (FACT,)))


async def _facts_from_unit_via_owner(
    client: OwnerClient, unit_id: int, customer_id: int | None,
) -> list[GraphFactView]:
    edges = await client.neighbors(
        unit_id, direction="outgoing", limit=200,
    )
    facts = []
    for edge in edges:
        view = _visible_fact(edge, customer_id)
        if view is not None:
            facts.append(view)
    return facts


async def search_research_facts_via_owner(
    client: OwnerClient, customer_id: int | None,
    dense_query: list[float], limit: int,
) -> list[ResearchFactHit]:
    unique: dict[str, ResearchFactHit] = {}
    for hit in await client.hybrid_search(
        customer_id=customer_id, dense_query=dense_query, limit=limit,
    ):
        if hit["kind"] == "fact":
            props = dict(hit.get("props") or {})
            if str(props.get("status") or "") != "active":
                continue
            view = fact_view(_record(str(hit["key"]), props, hit.get("id"), (FACT,)))
            unique.setdefault(view.id, ResearchFactHit(view, float(hit["score"]), int(hit.get("hop") or 0)))
            continue
        if hit["kind"] != "text_unit":
            continue
        unit_id = hit.get("id")
        if unit_id is None:
            continue
        for fact in await _facts_from_unit_via_owner(client, int(unit_id), customer_id):
            unique.setdefault(fact.id, ResearchFactHit(fact, float(hit["score"]), int(hit.get("hop") or 0)))
    return list(unique.values())[:limit]


async def question_facts_via_owner(
    client: OwnerClient, question_id: str, customer_id: int | None, limit: int,
) -> list[ResearchFactHit]:
    question = await find_question_via_owner(client, question_id, customer_id)
    if question is None or question.engine_id is None:
        return []
    edges = await client.neighbors(
        question.engine_id, direction="outgoing", labels=[DEPENDS_ON], limit=200,
    )
    hits: list[ResearchFactHit] = []
    for edge in edges:
        view = _visible_fact(edge, customer_id)
        if view is not None:
            hits.append(ResearchFactHit(view, 1.0, 0))
        if len(hits) >= limit:
            break
    return hits


async def neighbourhood_facts_via_owner(
    client: OwnerClient, customer_id: int | None, seeds: list[str], limit: int,
) -> list[ResearchFactHit]:
    if not seeds:
        return []
    entities = await client.read([{"label": ENTITY, "key": seed} for seed in seeds])
    unique: dict[str, ResearchFactHit] = {}
    for seed in seeds:
        name = f"{ENTITY}:{seed}"
        props = entities["values"].get(name)
        engine_id = entities["ids"].get(name)
        if props is None or engine_id is None:
            continue
        if not is_visible(str(props.get("scope_key") or ""), customer_id):
            continue
        edges = await client.neighbors(
            int(engine_id), direction="incoming", labels=[SUBJECT, OBJECT],
            limit=200,
        )
        for edge in edges:
            view = _visible_fact(edge, customer_id)
            if view is not None:
                unique.setdefault(view.id, ResearchFactHit(view, 1.0, 1))
            if len(unique) >= limit:
                return list(unique.values())
    return list(unique.values())


async def collect_research_hits_via_owner(
    client: OwnerClient, *, customer_id: int | None, question_id: str | None,
    dense_query: list[float], bound: int,
) -> list[ResearchFactHit]:
    direct = (
        await question_facts_via_owner(client, question_id, customer_id, bound)
        if question_id else []
    )
    hybrid = await search_research_facts_via_owner(client, customer_id, dense_query, bound)
    seeds = list(dict.fromkeys(
        node for hit in [*direct, *hybrid] for node in (hit.fact.source_id, hit.fact.target_id)
    ))
    expanded = (
        await neighbourhood_facts_via_owner(client, customer_id, seeds, bound)
        if seeds else []
    )
    unique: dict[str, ResearchFactHit] = {}
    for hit in [*direct, *hybrid, *expanded]:
        unique.setdefault(hit.fact.id, hit)
    return list(unique.values())


async def has_supported_facts_via_owner(
    client: OwnerClient, customer_id: int | None,
) -> bool:
    scopes = visible_scope_keys(customer_id)
    keys = [f"{INDEX_PREFIX}{scope}" for scope in scopes]
    result = await client.read([{"label": ENTITY, "key": key} for key in keys])
    return any(
        (result["values"].get(f"{ENTITY}:{key}") or {}).get("has_text_unit_facts")
        for key in keys
    )


async def load_text_units_via_owner(
    client: OwnerClient, unit_ids: list[str],
) -> list[Any]:
    if not unit_ids:
        return []
    result = await client.read([{"label": TEXT_UNIT, "key": key} for key in unit_ids])
    return [
        None if (props := result["values"].get(f"{TEXT_UNIT}:{key}")) is None
        else text_unit_view(_record(key, props, result["ids"].get(f"{TEXT_UNIT}:{key}"), (TEXT_UNIT,)))
        for key in unit_ids
    ]


async def supporting_units_via_owner(
    client: OwnerClient, fact: GraphFactView,
) -> list[Any]:
    if not fact.text_unit_refs:
        return []
    result = await client.read([
        {"label": TEXT_UNIT, "key": key} for key in fact.text_unit_refs
    ])
    units = []
    for key in fact.text_unit_refs:
        props = result["values"].get(f"{TEXT_UNIT}:{key}")
        units.append(
            None if props is None else text_unit_view(
                _record(key, props, result["ids"].get(f"{TEXT_UNIT}:{key}"), (TEXT_UNIT,))
            )
        )
    return units
