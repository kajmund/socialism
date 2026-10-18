"""Candidate-recall versus corpus-recall. UNCERTAIN is not MATCH."""

from __future__ import annotations

from overgraph_ingest.cerebras.prompt import MATCH, UNCERTAIN, Candidate, ParsedJudgment
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.gold_map import map_span
from overgraph_ingest.retrieval.index import StoredUnit


def relevant_keys(units: list[StoredUnit], gold: RetrievalGold) -> set[str]:
    keys: set[str] = set()
    for span in gold.relevant_units:
        mapped = map_span(units, span)
        for hit in mapped["hits"]:
            keys.add(str(hit["unit_key"]))
    return keys


def relevant_documents(units: list[StoredUnit], gold: RetrievalGold, keys: set[str]) -> set[str]:
    docs = {unit.relative_path for unit in units if unit.key in keys}
    if gold.relevant_documents:
        return set(gold.relevant_documents)
    return docs


def score_rerank(
    *,
    gold: RetrievalGold,
    candidates: list[Candidate],
    judgments: list[ParsedJudgment],
    corpus_relevant_keys: set[str],
    corpus_relevant_docs: set[str],
) -> dict[str, object]:
    candidate_keys = {item.key for item in candidates}
    relevant_in_candidates = candidate_keys & corpus_relevant_keys
    by_key = {item.key: item for item in candidates}
    matches = [row for row in judgments if row.label == MATCH]
    uncertain = [row for row in judgments if row.label == UNCERTAIN]
    match_keys = {row.key for row in matches}
    true_match = match_keys & corpus_relevant_keys
    false_match = match_keys - corpus_relevant_keys
    missed = relevant_in_candidates - match_keys
    match_docs = {by_key[key].relative_path for key in true_match if key in by_key}
    retrieval_docs = {item.relative_path for item in candidates} & corpus_relevant_docs
    return {
        "candidates": len(candidates),
        "relevant_in_candidates": len(relevant_in_candidates),
        "relevant_in_corpus": len(corpus_relevant_keys),
        "match": len(matches),
        "uncertain": len(uncertain),
        "uncertain_relevant": sum(1 for row in uncertain if row.key in corpus_relevant_keys),
        "precision": (len(true_match) / len(match_keys)) if match_keys else 0.0,
        "candidate_recall": (
            (len(true_match) / len(relevant_in_candidates)) if relevant_in_candidates else 0.0
        ),
        "corpus_recall": (
            (len(true_match) / len(corpus_relevant_keys)) if corpus_relevant_keys else 0.0
        ),
        "retrieval_document_coverage": (
            (len(retrieval_docs) / len(corpus_relevant_docs)) if corpus_relevant_docs else 0.0
        ),
        "corpus_document_recall": (
            (len(match_docs) / len(corpus_relevant_docs)) if corpus_relevant_docs else 0.0
        ),
        "documents_found": len(match_docs),
        "documents_expected": len(corpus_relevant_docs),
        "true_match_keys": sorted(true_match),
        "false_match_keys": sorted(false_match),
        "missed_in_candidates": sorted(missed),
        "gold_id": gold.id,
    }


def span_keys(units: list[StoredUnit], spans: list[GoldSpan]) -> set[str]:
    keys: set[str] = set()
    for span in spans:
        mapped = map_span(units, span)
        for hit in mapped["hits"]:
            keys.add(str(hit["unit_key"]))
    return keys


def score_negations(
    *,
    candidates: list[Candidate],
    judgments: list[ParsedJudgment],
    hard_keys: set[str],
    watch_keys: set[str],
) -> dict[str, object]:
    candidate_keys = {item.key for item in candidates}
    match_keys = {row.key for row in judgments if row.label == MATCH}
    hard_in = candidate_keys & hard_keys
    watch_in = candidate_keys & watch_keys
    hard_matched = match_keys & hard_keys
    watch_matched = match_keys & watch_keys
    return {
        "hard_negatives_in_candidates": len(hard_in),
        "hard_negatives_matched": len(hard_matched),
        "hard_negative_accept_rate": (len(hard_matched) / len(hard_in)) if hard_in else 0.0,
        "watch_negatives_in_candidates": len(watch_in),
        "watch_negatives_matched": len(watch_matched),
        "watch_negative_accept_rate": (len(watch_matched) / len(watch_in)) if watch_in else 0.0,
        "hard_matched_keys": sorted(hard_matched),
        "watch_matched_keys": sorted(watch_matched),
    }
