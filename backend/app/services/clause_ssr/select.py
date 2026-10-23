"""Versioned, diversity-aware, reproducible AnchorSet selection."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord
from app.services.ssr.similarity import cosine_similarity

from app.services.clause_ssr.anchors import (
    anchor_is_matchable,
    get_anchor,
    list_anchors,
)
from app.services.clause_ssr.graph import (
    find_by_prop,
    link,
    list_visible,
    now_ms,
    prop_int,
    prop_str,
    require_node,
    upsert_scoped,
)
from app.services.clause_ssr.keys import set_key
from app.services.clause_ssr.labels import ANCHOR, ANCHOR_SET, MEMBER_OF
from app.services.clause_ssr.types import Anchor, AnchorSet, EmbeddingSpec


def build_anchor_set(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    category: str,
    embedding: EmbeddingSpec,
    holdout_ids: tuple[str, ...] = (),
    max_per_polarity: int = 12,
) -> AnchorSet:
    candidates = [
        item
        for item in list_anchors(
            catalog,
            customer_id=scope.customer_id,
            statuses=("draft", "active"),
        )
        if item.scope_key == scope.scope_key
        and item.category == category
        and item.vector is not None
        and anchor_is_matchable(catalog, item)
        and _same_embedding(item.embedding, embedding)
        and item.source_unit_id not in holdout_ids
        and item.content_hash not in holdout_ids
    ]
    selected = _diverse_pick(candidates, max_per_polarity)
    version = _next_version(catalog, scope.scope_key, category)
    key = set_key(scope.scope_key, category, version)
    _deactivate_sets(catalog, scope, category)
    row = upsert_scoped(
        catalog,
        kind=ANCHOR_SET,
        key=key,
        scope=scope,
        props={
            "version": version,
            "category": category,
            "status": "active",
            "selection_method": "deterministic_diversity",
            "embedding_model": embedding.model,
            "embedding_revision": embedding.revision,
            "embedding_dimension": embedding.dimension,
            "holdout_ids": ",".join(holdout_ids),
            "created_at_ms": now_ms(),
        },
    )
    for anchor in selected:
        link(catalog, require_node(catalog, ANCHOR, anchor.id), row, label=MEMBER_OF)
    return _from_row(catalog, row)


def list_anchor_sets(
    catalog: Catalog,
    *,
    customer_id: int | None,
    active_only: bool = False,
) -> list[AnchorSet]:
    items = [_from_row(catalog, row) for row in list_visible(catalog, ANCHOR_SET, customer_id)]
    if active_only:
        items = [item for item in items if item.status == "active"]
    items.sort(key=lambda item: (item.category, item.version))
    return items


def get_anchor_set(catalog: Catalog, set_id: str) -> AnchorSet:
    return _from_row(catalog, require_node(catalog, ANCHOR_SET, set_id))


def _diverse_pick(candidates: list[Anchor], max_per_polarity: int) -> list[Anchor]:
    picked: list[Anchor] = []
    for polarity in ("positive", "negative"):
        group = [item for item in candidates if item.polarity == polarity]
        group.sort(key=lambda item: (item.content_hash, item.source_unit_id, item.id))
        picked.extend(_greedy_diverse(group, max_per_polarity))
    return picked


def _greedy_diverse(group: list[Anchor], limit: int) -> list[Anchor]:
    if not group:
        return []
    chosen = [group[0]]
    remaining = group[1:]
    while remaining and len(chosen) < limit:
        remaining.sort(key=lambda item: (_min_sim(item, chosen), item.content_hash, item.id))
        next_item = remaining.pop(0)
        chosen.append(next_item)
    return chosen


def _min_sim(candidate: Anchor, chosen: list[Anchor]) -> float:
    if candidate.vector is None:
        return 0.0
    return min(
        cosine_similarity(list(candidate.vector), list(item.vector))
        for item in chosen
        if item.vector is not None
    )


def _next_version(catalog: Catalog, scope_key: str, category: str) -> int:
    highest = 0
    for row in find_by_prop(catalog, ANCHOR_SET, "category", category):
        if prop_str(row, "scope_key") != scope_key:
            continue
        highest = max(highest, prop_int(row, "version"))
    return highest + 1


def _deactivate_sets(
    catalog: Catalog, scope: KnowledgeTenantScope, category: str,
) -> None:
    for item in list_anchor_sets(catalog, customer_id=scope.customer_id):
        if item.scope_key != scope.scope_key or item.category != category:
            continue
        if item.status != "active":
            continue
        upsert_scoped(
            catalog,
            kind=ANCHOR_SET,
            key=item.id,
            scope=scope,
            props=_set_props(item, "superseded"),
        )


def _set_props(item: AnchorSet, status: str) -> dict[str, object]:
    return {
        "version": item.version,
        "category": item.category,
        "status": status,
        "selection_method": item.selection_method,
        "embedding_model": item.embedding.model,
        "embedding_revision": item.embedding.revision,
        "embedding_dimension": item.embedding.dimension,
        "holdout_ids": ",".join(item.holdout_ids),
        "created_at_ms": item.created_at_ms,
    }


def _same_embedding(left: EmbeddingSpec, right: EmbeddingSpec) -> bool:
    return (
        left.model == right.model
        and left.revision == right.revision
        and left.dimension == right.dimension
    )


def _from_row(catalog: Catalog, row: GraphRecord) -> AnchorSet:
    member_ids: list[str] = []
    if row.engine_id is not None:
        for engine_id in catalog.neighbors(
            row.engine_id, direction="incoming", edge_label_filter=[MEMBER_OF],
        ):
            node = catalog.get(engine_id)
            if node is None:
                continue
            try:
                anchor = get_anchor(catalog, node.key)
            except KeyError:
                continue
            if anchor.status in {"draft", "active"} and anchor_is_matchable(
                catalog, anchor
            ):
                member_ids.append(node.key)
    holdout = tuple(part for part in prop_str(row, "holdout_ids").split(",") if part)
    return AnchorSet(
        id=row.key,
        version=prop_int(row, "version", 1),
        category=prop_str(row, "category"),
        status=prop_str(row, "status") or "draft",  # type: ignore[arg-type]
        selection_method="deterministic_diversity",
        embedding=EmbeddingSpec(
            model=prop_str(row, "embedding_model"),
            revision=prop_str(row, "embedding_revision"),
            dimension=prop_int(row, "embedding_dimension"),
        ),
        holdout_ids=holdout,
        member_ids=tuple(sorted(member_ids)),
        scope_key=prop_str(row, "scope_key"),
        created_at_ms=prop_int(row, "created_at_ms"),
    )

