"""Hybrid fact retrieval and bounded neighbourhood expansion."""

import math
import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact


@dataclass(frozen=True)
class FactHit:
    fact: GraphFact
    score: float
    hop: int


def _visible(customer_id: int):
    return GraphFact.scope_key.in_((f"customer:{customer_id}", "shared"))


async def hybrid_facts(
    session: AsyncSession, *, customer_id: int, query: str,
    embedding: list[float] | None = None, limit: int = 20,
) -> list[FactHit]:
    if not query.strip() or limit < 1:
        raise ValueError("query and positive limit required")
    terms = re.findall(r"\w+", query.casefold())
    if session.bind and session.bind.dialect.name == "postgresql":
        from sqlalchemy import func
        lexical = func.to_tsvector("simple", GraphFact.fact_text).op("@@")(
            func.websearch_to_tsquery("simple", query)
        )
    else:
        lexical = or_(*(GraphFact.normalized_text.ilike(f"%{term}%") for term in terms))
    lexical_rows = list((await session.scalars(select(GraphFact).where(
        _visible(customer_id), GraphFact.status == "active", lexical,
    ).limit(max(100, limit * 5)))).all())
    # Portable bounded scan for embeddings; Postgres FTS index serves lexical retrieval.
    semantic_rows = list((await session.scalars(select(GraphFact).where(
        _visible(customer_id), GraphFact.status == "active",
        GraphFact.embedding.is_not(None),
    ).limit(2000))).all()) if embedding is not None else []
    lexical_rank = {row.id: rank for rank, row in enumerate(lexical_rows, 1)}
    semantic_rank = {
        row.id: rank for rank, row in enumerate(
            sorted(semantic_rows, key=lambda row: _cosine(embedding, row.embedding), reverse=True), 1
        )
    }
    rows = {row.id: row for row in (*lexical_rows, *semantic_rows)}
    return sorted((
        FactHit(
            row,
            (1 / (50 + lexical_rank[row.id]) if row.id in lexical_rank else 0)
            + (1 / (50 + semantic_rank[row.id]) if row.id in semantic_rank else 0),
            0,
        )
        for row in rows.values()
    ), key=lambda hit: hit.score, reverse=True)[:limit]


def _cosine(first: list[float] | None, second: list[float] | None) -> float:
    if not first or not second or len(first) != len(second):
        return -1.0
    length = math.sqrt(sum(x * x for x in first) * sum(x * x for x in second))
    return sum(x * y for x, y in zip(first, second, strict=True)) / length if length else -1.0


async def neighbourhood(
    session: AsyncSession, *, customer_id: int, seeds: list[str],
    max_hops: int = 2, limit: int = 100,
) -> list[FactHit]:
    if max_hops < 1 or max_hops > 4 or limit < 1:
        raise ValueError("hops must be 1..4 and limit positive")
    visited: set[str] = set()
    frontier = set(seeds)
    output: list[FactHit] = []
    for hop in range(1, max_hops + 1):
        if not frontier or len(output) >= limit:
            break
        rows = list((await session.scalars(select(GraphFact).where(
            _visible(customer_id), GraphFact.status == "active",
            or_(GraphFact.source_id.in_(frontier), GraphFact.target_id.in_(frontier)),
        ).limit(limit * 3))).all())
        next_frontier: set[str] = set()
        for row in rows:
            if row.id in visited:
                continue
            visited.add(row.id)
            output.append(FactHit(row, 1 / hop, hop))
            next_frontier.update((row.source_id, row.target_id))
            if len(output) == limit:
                break
        frontier = next_frontier - frontier
    return output
