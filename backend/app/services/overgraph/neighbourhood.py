"""Bounded multi-hop fact traversal over the knowledge catalog.

Facts are edges (``fact --SUBJECT--> source``, ``fact --OBJECT--> target``), so a hop is the
incoming ``SUBJECT``/``OBJECT`` facts of the current frontier. Validity is decided in the
catalog on every step: an invalid fact never contributes its endpoints to the next
frontier, so it can never open a path to further candidates.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import (
    DOCUMENT_VERSION,
    ENTITY,
    FACT,
    OBJECT,
    SUBJECT,
    visible_scope_keys,
)
from app.services.overgraph.model import GraphFactView, GraphRecord
from app.services.overgraph.research import ResearchFactHit
from app.services.overgraph.views import fact_view


def _valid(catalog: Catalog, engine_id: int, customer_id: int | None, now: datetime) -> GraphFactView | None:
    row = catalog.get(engine_id)
    if row is None or FACT not in row.labels:
        return None
    if str(row.props.get("scope_key") or "") not in visible_scope_keys(customer_id):
        return None
    if str(row.props.get("status") or "") != "active":
        return None
    view = fact_view(row)
    if view.valid_at is not None and view.valid_at > now:
        return None
    if view.invalid_at is not None and now >= view.invalid_at:
        return None
    return view


def _endpoints(row: GraphRecord) -> tuple[str, str]:
    return (
        str(row.props.get("source_key") or ""),
        str(row.props.get("target_key") or ""),
    )


def _facts_touching(catalog: Catalog, keys: set[str]) -> list[int]:
    engine_ids: set[int] = set()
    for key in sorted(keys):
        entity = catalog.get_by_key(ENTITY, key)
        if entity is None or entity.engine_id is None:
            entity = catalog.get_by_key(DOCUMENT_VERSION, key)
        if entity is None or entity.engine_id is None:
            continue
        engine_ids.update(
            catalog.neighbors(
                entity.engine_id, direction="incoming", edge_label_filter=[SUBJECT, OBJECT],
            )
        )
    return sorted(engine_ids)


def neighbourhood_facts(
    catalog: Catalog,
    *,
    customer_id: int | None,
    seeds: list[str],
    max_hops: int = 2,
    limit: int = 100,
    now: datetime | None = None,
) -> list[ResearchFactHit]:
    """Facts within ``max_hops`` of the seeds, scored ``1/hop``, shortest path first."""
    if max_hops < 1 or max_hops > 4 or limit < 1:
        raise ValueError("hops must be 1..4 and limit positive")
    moment = now or datetime.now(UTC)
    visited: set[str] = set()
    frontier = {seed for seed in seeds if seed}
    output: list[ResearchFactHit] = []
    for hop in range(1, max_hops + 1):
        if not frontier or len(output) >= limit:
            break
        next_frontier: set[str] = set()
        for engine_id in _facts_touching(catalog, frontier):
            view = _valid(catalog, engine_id, customer_id, moment)
            if view is None or view.id in visited:
                continue
            visited.add(view.id)
            output.append(ResearchFactHit(view, 1 / hop, hop))
            row = catalog.get(engine_id)
            if row is not None:
                next_frontier.update(key for key in _endpoints(row) if key)
            if len(output) >= limit:
                break
        frontier = next_frontier - frontier
    return output
