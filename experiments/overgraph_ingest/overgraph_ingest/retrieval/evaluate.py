"""Recall@k, Precision@k, document coverage, ranking quality, and miss taxonomy."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold, matching_spans
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit


@dataclass
class UnitJudgement:
    key: str
    relative_path: str
    kind: str
    span: str
    rank: int | None = None
    exhaustive_rank: int | None = None


@dataclass
class StrategyMetrics:
    mode: str
    k: int
    retrieved: int
    relevant: int
    recall: float
    precision: float
    document_coverage: float
    documents_found: int
    documents_expected: int
    unique_documents: int
    mrr: float
    document_mrr: float
    ndcg: float
    first_relevant_rank: int | None
    first_relevant_document_rank: int | None
    hard_negatives_in_topk: int
    hard_negative_ranks: list[dict[str, object]] = field(default_factory=list)
    absent: list[UnitJudgement] = field(default_factory=list)
    unretrieved: list[UnitJudgement] = field(default_factory=list)
    low_rank: list[UnitJudgement] = field(default_factory=list)
    hits: list[dict[str, object]] = field(default_factory=list)


def judge_units(
    units: list[StoredUnit], gold: RetrievalGold
) -> tuple[set[str], set[str], list[UnitJudgement]]:
    relevant: set[str] = set()
    negatives: set[str] = set()
    absent: list[UnitJudgement] = []
    found_relevant: set[str] = set()
    found_negative: set[str] = set()
    for unit in units:
        if matching_spans(unit.text, unit.relative_path, gold.relevant_units):
            relevant.add(unit.key)
            found_relevant.add(f"{unit.relative_path}\0{unit.text}")
        if matching_spans(unit.text, unit.relative_path, gold.hard_negatives):
            negatives.add(unit.key)
            found_negative.add(f"{unit.relative_path}\0{unit.text}")
    for span in gold.relevant_units:
        if not _span_present(span, units):
            absent.append(
                UnitJudgement(
                    key="",
                    relative_path=span.relative_path,
                    kind="absent",
                    span=span.contains,
                )
            )
    return relevant, negatives, absent


def evaluate_strategy(
    *,
    mode: str,
    k: int,
    gold: RetrievalGold,
    hits: list[SearchHit],
    exhaustive: list[SearchHit],
    relevant_keys: set[str],
    negative_keys: set[str],
    absent: list[UnitJudgement],
) -> StrategyMetrics:
    top = [hit for hit in hits if hit.rank <= k][:k]
    retrieved_relevant = [hit for hit in top if hit.key in relevant_keys]
    documents_found = {hit.relative_path for hit in retrieved_relevant}
    expected_docs = gold.relevant_documents
    exhaustive_rank = {hit.key: hit.rank for hit in exhaustive}
    engine_rank = {hit.key: hit.rank for hit in hits}
    unretrieved: list[UnitJudgement] = []
    low_rank: list[UnitJudgement] = []
    for key in relevant_keys:
        found_at = engine_rank.get(key)
        full_at = exhaustive_rank.get(key)
        if found_at is not None and found_at <= k:
            continue
        judgement = UnitJudgement(
            key=key,
            relative_path=_path_for(key, hits, exhaustive),
            kind="low_rank" if full_at is not None and full_at <= k else "unretrieved",
            span="",
            rank=found_at,
            exhaustive_rank=full_at,
        )
        if judgement.kind == "low_rank":
            low_rank.append(judgement)
        else:
            unretrieved.append(judgement)
    relevant_count = len(relevant_keys)
    ranking = ranking_quality(top, gold, relevant_keys, negative_keys)
    return StrategyMetrics(
        mode=mode,
        k=k,
        retrieved=len(top),
        relevant=relevant_count,
        recall=(len(retrieved_relevant) / relevant_count) if relevant_count else 0.0,
        precision=(len(retrieved_relevant) / len(top)) if top else 0.0,
        document_coverage=(len(documents_found) / len(expected_docs)) if expected_docs else 0.0,
        documents_found=len(documents_found),
        documents_expected=len(expected_docs),
        unique_documents=len({hit.relative_path for hit in top}),
        mrr=ranking["mrr"],
        document_mrr=ranking["document_mrr"],
        ndcg=ranking["ndcg"],
        first_relevant_rank=ranking["first_relevant_rank"],
        first_relevant_document_rank=ranking["first_relevant_document_rank"],
        hard_negatives_in_topk=sum(1 for hit in top if hit.key in negative_keys),
        hard_negative_ranks=ranking["hard_negative_ranks"],
        absent=absent,
        unretrieved=unretrieved,
        low_rank=low_rank,
        hits=[_hit_payload(hit, relevant_keys, negative_keys) for hit in top],
    )


def ranking_quality(
    hits: list[SearchHit],
    gold: RetrievalGold,
    relevant_keys: set[str],
    negative_keys: set[str],
) -> dict[str, object]:
    first_relevant = min((hit.rank for hit in hits if hit.key in relevant_keys), default=None)
    relevant_docs = set(gold.relevant_documents)
    first_relevant_document = min(
        (hit.rank for hit in hits if hit.relative_path in relevant_docs),
        default=None,
    )
    gains = [1.0 if hit.key in relevant_keys else 0.0 for hit in hits]
    return {
        "first_relevant_rank": first_relevant,
        "first_relevant_document_rank": first_relevant_document,
        "mrr": (1.0 / first_relevant) if first_relevant else 0.0,
        "document_mrr": (1.0 / first_relevant_document) if first_relevant_document else 0.0,
        "ndcg": ndcg(gains, relevant_count=len(relevant_keys)),
        "hard_negative_ranks": [
            {
                "relative_path": hit.relative_path,
                "rank": hit.rank,
                "key": hit.key,
            }
            for hit in hits
            if hit.key in negative_keys
        ],
    }


def ndcg(gains: list[float], *, relevant_count: int) -> float:
    if not gains or relevant_count <= 0:
        return 0.0
    ideal = [1.0] * min(relevant_count, len(gains))
    return _dcg(gains) / _dcg(ideal) if ideal else 0.0


def _dcg(gains: list[float]) -> float:
    return sum(gain / math.log2(index + 1) for index, gain in enumerate(gains, start=1))


def metrics_payload(metric: StrategyMetrics) -> dict[str, object]:
    return {
        "mode": metric.mode,
        "k": metric.k,
        "retrieved": metric.retrieved,
        "relevant": metric.relevant,
        "recall": metric.recall,
        "precision": metric.precision,
        "document_coverage": metric.document_coverage,
        "documents_found": metric.documents_found,
        "documents_expected": metric.documents_expected,
        "unique_documents": metric.unique_documents,
        "mrr": metric.mrr,
        "document_mrr": metric.document_mrr,
        "ndcg": metric.ndcg,
        "first_relevant_rank": metric.first_relevant_rank,
        "first_relevant_document_rank": metric.first_relevant_document_rank,
        "hard_negatives_in_topk": metric.hard_negatives_in_topk,
        "hard_negative_ranks": metric.hard_negative_ranks,
        "absent": [item.__dict__ for item in metric.absent],
        "unretrieved": [item.__dict__ for item in metric.unretrieved],
        "low_rank": [item.__dict__ for item in metric.low_rank],
        "hits": metric.hits,
    }


def _span_present(span: GoldSpan, units: list[StoredUnit]) -> bool:
    return any(
        unit.relative_path == span.relative_path and span.contains in unit.text for unit in units
    )


def _path_for(key: str, hits: list[SearchHit], exhaustive: list[SearchHit]) -> str:
    for hit in hits:
        if hit.key == key:
            return hit.relative_path
    for hit in exhaustive:
        if hit.key == key:
            return hit.relative_path
    return ""


def _hit_payload(hit: SearchHit, relevant: set[str], negatives: set[str]) -> dict[str, object]:
    label = "relevant" if hit.key in relevant else "hard_negative" if hit.key in negatives else "other"
    return {
        "rank": hit.rank,
        "score": hit.score,
        "key": hit.key,
        "relative_path": hit.relative_path,
        "label": label,
        "text": hit.text[:240],
    }
