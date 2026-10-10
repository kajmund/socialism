"""Budgeted traversal. Jev scores several candidates in one call."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.config import settings
from app.jev.system import JevSystemOne, parse_noul
from app.services.research.fast_controller import research_jev_model
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import FACT, TEXT_UNIT
from app.services.overgraph.model import KnowledgeHit
from app.services.overgraph.retrieval import (
    bounded_traverse,
    hybrid_search,
    rank_seeds,
    top_neighbors,
)


@dataclass(frozen=True)
class TraversalBudget:
    max_depth: int = 3
    max_candidates: int = 16
    max_jev: int = 8


@dataclass(frozen=True)
class TraversalResult:
    seeds: list[KnowledgeHit]
    ranked: list[KnowledgeHit]
    selected: list[KnowledgeHit]
    evidence: list[KnowledgeHit]


class CandidateJudge:
    """NOUL over many traversal candidates in one Jev call."""

    def __init__(self, client: JevSystemOne, prompt: dict[str, object]) -> None:
        self.client = client
        self.prompt = prompt

    async def score(self, question: str, candidates: Sequence[KnowledgeHit]) -> dict[str, float]:
        if not candidates:
            return {}
        result = await self.client.ask(
            state={
                "question": question,
                "candidates": [
                    {"id": hit.key, "kind": hit.kind, "text": hit.text} for hit in candidates
                ],
            },
            questions={
                hit.key: {**self.prompt, "instructions": f"{self.prompt.get('instructions', '')} {hit.key}"}
                for hit in candidates
            },
            model=research_jev_model(),
            timeout_seconds=settings.jev_timeout_seconds,
        )
        return {hit.key: parse_noul(result.answers, hit.key) for hit in candidates}


async def traverse_question(
    catalog: Catalog,
    *,
    customer_id: int | None,
    question: str,
    dense_query: Sequence[float],
    judge: CandidateJudge | None = None,
    budget: TraversalBudget | None = None,
    sparse_query: Sequence[tuple[int, float]] | None = None,
) -> TraversalResult:
    limits = budget or TraversalBudget()
    seeds = hybrid_search(
        catalog, customer_id=customer_id, dense_query=dense_query,
        limit=limits.max_candidates, sparse_query=sparse_query,
    )
    ranked = rank_seeds(
        catalog, customer_id=customer_id, seeds=seeds, max_results=limits.max_candidates,
    ) or seeds
    shortlist = ranked[:limits.max_jev]
    selected = list(shortlist)
    if judge is not None and shortlist:
        scores = await judge.score(question, shortlist)
        selected = [hit for hit in shortlist if scores.get(hit.key, 0.0) > 0.1]
    evidence: list[KnowledgeHit] = []
    seen: set[str] = set()
    for hit in selected:
        label = FACT if hit.kind == "fact" else TEXT_UNIT
        for neighbor in (
            *top_neighbors(catalog, customer_id=customer_id, key=hit.key, label=label),
            *bounded_traverse(
                catalog, customer_id=customer_id, key=hit.key, label=label,
                max_depth=limits.max_depth,
            ),
        ):
            if neighbor.key in seen:
                continue
            seen.add(neighbor.key)
            evidence.append(neighbor)
            if len(evidence) >= limits.max_candidates:
                return TraversalResult(seeds, ranked, selected, evidence)
    return TraversalResult(seeds, ranked, selected, evidence)
