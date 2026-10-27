"""Hybrid fact retrieval: Tantivy supplies lexical candidates, OverGraph decides truth.

The index is a derived projection, so every lexical hit is hydrated from the knowledge
catalog and re-checked for status, validity window and tenant visibility **before** the
final candidate budget is applied. Invalid hits never consume budget: the index is paged
until the budget is filled or the candidate stream is exhausted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import FACT, visible_scope_keys
from app.services.overgraph.model import GraphFactView
from app.services.overgraph.research import ResearchFactHit, search_research_facts
from app.services.overgraph.views import fact_view
from app.services.tantivy_index import TextUnitIndex, pending_updates, read_watermark

RRF_K = 50
FACT_INDEX_PAGE = 100


class FactIndexStaleError(RuntimeError):
    """The lexical index does not yet reflect the current graph revision."""


@dataclass(frozen=True)
class LexicalCoverage:
    """How complete the lexical half of a hybrid search was."""

    stale: bool
    pending_changes: int


def fact_index_lag(catalog: Catalog, index_dir: Path, *, now_ms: int | None = None) -> int:
    """Graph changes newer than the index watermark (0 means the index is caught up)."""
    return pending_updates(
        catalog, watermark_ms=read_watermark(Path(index_dir)), now_ms=now_ms,
    )


def ensure_fact_index_current(
    catalog: Catalog, index_dir: Path, *, now_ms: int | None = None,
) -> None:
    """Refuse to present a lagging index as a complete lexical search."""
    pending = fact_index_lag(catalog, index_dir, now_ms=now_ms)
    if pending:
        raise FactIndexStaleError(
            f"fact index is {pending} change(s) behind the graph at "
            f"{Path(index_dir)}; reconcile it before hybrid retrieval"
        )


def _hydrate(catalog: Catalog, key: str, customer_id: int | None, now: datetime) -> GraphFactView | None:
    row = catalog.get_by_key(FACT, key)
    if row is None:
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


def _lexical_candidates(
    catalog: Catalog,
    index: TextUnitIndex,
    *,
    query: str,
    customer_id: int | None,
    budget: int,
    now: datetime,
) -> list[GraphFactView]:
    """BM25 candidates hydrated from OverGraph, paged so invalid hits cannot hide recall."""
    tenants = tuple(visible_scope_keys(customer_id))
    candidates: list[GraphFactView] = []
    seen: set[str] = set()
    offset = 0
    for search in (index.search_fact_keys, index.search_subword_keys):
        offset = 0
        while len(candidates) < budget:
            page = search(query, tenant_ids=tenants, limit=FACT_INDEX_PAGE, offset=offset)
            if not page:
                break
            for hit in page:
                if hit.key in seen:
                    continue
                seen.add(hit.key)
                view = _hydrate(catalog, hit.key, customer_id, now)
                if view is not None:
                    candidates.append(view)
                    if len(candidates) == budget:
                        break
            offset += FACT_INDEX_PAGE
            if len(page) < FACT_INDEX_PAGE:
                break
    return candidates


def _dense_candidates(
    catalog: Catalog, *, customer_id: int | None, dense_query: list[float] | None,
    budget: int, now: datetime,
) -> list[GraphFactView]:
    if dense_query is None:
        return []
    valid: list[GraphFactView] = []
    for hit in search_research_facts(catalog, customer_id, dense_query, budget):
        view = hit.fact
        if view.scope_key not in visible_scope_keys(customer_id) or view.status != "active":
            continue
        if view.valid_at is not None and view.valid_at > now:
            continue
        if view.invalid_at is not None and now >= view.invalid_at:
            continue
        valid.append(view)
    return valid


def _ranked(views: list[GraphFactView]) -> dict[str, int]:
    return {view.id: rank for rank, view in enumerate(views, 1)}


def hybrid_fact_hits(
    catalog: Catalog,
    index: TextUnitIndex,
    *,
    customer_id: int | None,
    query: str,
    limit: int = 20,
    dense_query: list[float] | None = None,
    now: datetime | None = None,
) -> list[ResearchFactHit]:
    """Reciprocal-rank fusion of lexical Tantivy hits and dense OverGraph hits."""
    if not query.strip() or limit < 1:
        raise ValueError("query and positive limit required")
    moment = now or datetime.now(UTC)
    budget = max(100, limit * 5)
    lexical = _lexical_candidates(
        catalog, index, query=query, customer_id=customer_id, budget=budget, now=moment,
    )
    dense = _dense_candidates(
        catalog, customer_id=customer_id, dense_query=dense_query, budget=budget, now=moment,
    )
    lexical_rank = _ranked(lexical)
    dense_rank = _ranked(dense)
    merged: dict[str, GraphFactView] = {view.id: view for view in (*lexical, *dense)}
    scored = [
        ResearchFactHit(
            view,
            (1 / (RRF_K + lexical_rank[view.id]) if view.id in lexical_rank else 0.0)
            + (1 / (RRF_K + dense_rank[view.id]) if view.id in dense_rank else 0.0),
            0,
        )
        for view in merged.values()
    ]
    scored.sort(key=lambda hit: (-hit.score, hit.fact.id))
    return scored[:limit]


async def _hydrate_via_owner(client, key: str, customer_id: int | None, now: datetime):
    from app.services.overgraph.model import GraphRecord

    response = await client.read([{"label": FACT, "key": key}])
    props = response["values"].get(f"{FACT}:{key}")
    if props is None:
        return None
    if str(props.get("scope_key") or "") not in visible_scope_keys(customer_id):
        return None
    if str(props.get("status") or "") != "active":
        return None
    view = fact_view(GraphRecord(
        key=key, labels=(FACT,), props=dict(props),
        engine_id=response["ids"].get(f"{FACT}:{key}"),
    ))
    if view.valid_at is not None and view.valid_at > now:
        return None
    if view.invalid_at is not None and now >= view.invalid_at:
        return None
    return view


async def hybrid_fact_hits_via_owner(
    client,
    index: TextUnitIndex,
    *,
    customer_id: int | None,
    query: str,
    limit: int = 20,
    dense_query: list[float] | None = None,
    now: datetime | None = None,
) -> list[ResearchFactHit]:
    """Owner-backed equivalent of ``hybrid_fact_hits``; Tantivy stays the lexical side."""
    from app.services.overgraph.research_owner import search_research_facts_via_owner

    if not query.strip() or limit < 1:
        raise ValueError("query and positive limit required")
    moment = now or datetime.now(UTC)
    budget = max(100, limit * 5)
    tenants = tuple(visible_scope_keys(customer_id))
    seen: set[str] = set()
    lexical: list[GraphFactView] = []
    for search in (index.search_fact_keys, index.search_subword_keys):
        offset = 0
        while len(lexical) < budget:
            page = search(query, tenant_ids=tenants, limit=FACT_INDEX_PAGE, offset=offset)
            if not page:
                break
            for hit in page:
                if hit.key in seen:
                    continue
                seen.add(hit.key)
                view = await _hydrate_via_owner(client, hit.key, customer_id, moment)
                if view is not None:
                    lexical.append(view)
                    if len(lexical) == budget:
                        break
            offset += FACT_INDEX_PAGE
            if len(page) < FACT_INDEX_PAGE:
                break
    dense = (
        [] if dense_query is None
        else [hit.fact for hit in await search_research_facts_via_owner(
            client, customer_id, dense_query, budget,
        )]
    )
    lexical_rank = _ranked(lexical)
    dense_rank = _ranked(dense)
    merged = {view.id: view for view in (*lexical, *dense)}
    scored = [
        ResearchFactHit(
            view,
            (1 / (RRF_K + lexical_rank[view.id]) if view.id in lexical_rank else 0.0)
            + (1 / (RRF_K + dense_rank[view.id]) if view.id in dense_rank else 0.0),
            0,
        )
        for view in merged.values()
    ]
    scored.sort(key=lambda hit: (-hit.score, hit.fact.id))
    return scored[:limit]
