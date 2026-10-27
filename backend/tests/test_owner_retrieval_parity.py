"""Owner hybrid retrieval must match the direct catalog ranking exactly."""

from __future__ import annotations

import math

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import FACT, scope_label
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.research import collect_research_hits
from app.services.overgraph.research_owner import collect_research_hits_via_owner

DIMENSION = 32
GROUPS = 4
PER_GROUP = 10
BOUND = 20


def _fact(index: int) -> dict:
    group = index % GROUPS
    vector = [0.0] * DIMENSION
    vector[group] = 1.0
    key = f"retrieval-fact-{index}"
    return {
        "labels": [FACT, scope_label("customer:1")],
        "key": key,
        "props": {
            "scope_key": "customer:1",
            "predicate": "legal.rule",
            "status": "active",
            "source_key": f"missing-src-{group}",
            "target_key": f"missing-target-{group}",
            "fact_text": f"fact {index}",
            "attributes_json": "{}",
            "source_refs_json": "[]",
            "created_at_ms": index,
        },
        "dense_vector": vector,
    }


async def _seed_owner(client, rows: list[dict]) -> None:
    for start in range(0, len(rows), 25):
        await client.mutate(
            f"seed-retrieval-{start}",
            {"upsert_nodes": rows[start:start + 25]}, kind="batch",
        )


def _recall_at(ids: list[str], relevant: set[str], k: int) -> float:
    return len(set(ids[:k]) & relevant) / len(relevant) if relevant else 0.0


def _ndcg_at(ids: list[str], relevant: set[str], k: int) -> float:
    gains = [1.0 if key in relevant else 0.0 for key in ids[:k]]
    dcg = sum(gain / math.log2(position + 2) for position, gain in enumerate(gains))
    ideal = sum(1 / math.log2(position + 2) for position in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


async def test_owner_hybrid_retrieval_matches_direct_ranking(tmp_path):
    direct = open_catalog(tmp_path / "direct", kind="knowledge", dimension=DIMENSION)
    rows = [_fact(index) for index in range(GROUPS * PER_GROUP)]
    for row in rows:
        direct.upsert_node(
            row["labels"], row["key"], props=row["props"],
            dense_vector=row["dense_vector"],
        )
    client = get_owner_runtime().require_client()
    await _seed_owner(client, rows)
    try:
        for group in range(GROUPS):
            query = [0.0] * DIMENSION
            query[group] = 1.0
            local = collect_research_hits(
                direct, customer_id=1, question_id=None,
                dense_query=query, bound=BOUND,
            )
            owner = await collect_research_hits_via_owner(
                client, customer_id=1, question_id=None,
                dense_query=query, bound=BOUND,
            )
            local_ids = [hit.fact.id for hit in local]
            owner_ids = [hit.fact.id for hit in owner]
            assert owner_ids == local_ids
            assert [hit.score for hit in owner] == [hit.score for hit in local]
            relevant = {f"retrieval-fact-{index}" for index in range(group, GROUPS * PER_GROUP, GROUPS)}
            assert _recall_at(owner_ids, relevant, BOUND) == 1.0
            assert _recall_at(owner_ids, relevant, 50) == 1.0
            assert _ndcg_at(owner_ids, relevant, 20) == 1.0
    finally:
        direct.close()
