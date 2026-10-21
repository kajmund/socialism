"""Optional Step B: answer_cell on frozen BM25 candidate lists.

This is deliberately separate from Step A. It reuses the existing P0 prompt,
the existing five-unit answer_cell contract, and frozen candidate lists. It
does not rerank, classify, or change the retriever.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean

from overgraph_ingest.jev.candidates import context_from_units
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.bm25_paging import (
    FrozenCandidateList,
    candidate_list_from_arm,
)
from overgraph_ingest.retrieval.evidence_gold import (
    CellEvidenceGold,
    group_evidence_keys,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.cells import answer_without_classify
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN, CellResult
from overgraph_ingest.tabular.gold import USER_QUESTIONS

TOP_K = 5
TRUE_ANSWER = "true_answer"
FALSE_ANSWER = "false_answer"
MISS = "miss"
CORRECT_NOT_FOUND = "correct_not_found"
ABSTENTION = "abstention"
ERROR = "error"


@dataclass
class AnswerArm:
    arm: str
    cell: CellEvidenceGold
    result: CellResult
    relevant_keys: set[str]


def run_bm25_answer_test(
    payload: dict[str, object],
    *,
    units: list[StoredUnit],
    cells: list[CellEvidenceGold],
    structures: dict[str, dict[str, object]] | None = None,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    jev: JevClient | None = None,
    profile: str | None = None,
    top_k: int = TOP_K,
) -> dict[str, object]:
    if top_k != TOP_K:
        raise ValueError("BM25 answer test keeps the existing five-unit budget")
    profile_name, profile_payload = _profile(payload, profile)
    document = profile_payload.get("document") or {}
    rows = {
        (str(row["question_id"]), str(row["relative_path"])): row
        for row in (document.get("rows") or [])
        if isinstance(row, dict)
    }
    if not rows:
        raise RuntimeError("BM25 answer test needs document-local candidate rows")
    if jev is None:
        if not typesafe_api_key:
            raise ValueError("--typesafe-api-key is required for --bm25-answer-test")
        jev = HttpJevClient(api_key=typesafe_api_key, base_url=typesafe_base_url)
    context = context_from_units(units, structures or {})
    by_key = {unit.key: unit for unit in units}
    arms = ("dense_bm25", "hybrid_current")
    results: list[AnswerArm] = []
    errors: list[dict[str, object]] = []
    for cell in cells:
        if cell.answerability == "not_evaluated":
            continue
        row = rows.get((cell.question_id, cell.relative_path))
        if row is None:
            raise RuntimeError(
                f"answer cell is missing a frozen candidate row: {cell.question_id}/{cell.relative_path}"
            )
        local = [unit for unit in units if unit.relative_path == cell.relative_path]
        relevant = group_evidence_keys(cell.groups, local)
        for arm in arms:
            candidates = (row["arms"][arm].get("candidates") or [])[:TOP_K]
            hits = _hits(candidates, by_key)
            retrieval = {
                "k": TOP_K,
                "strategy": arm,
                "candidate_keys": [hit.key for hit in hits],
                "question": USER_QUESTIONS[cell.question_id],
            }
            result = answer_without_classify(
                relative_path=cell.relative_path,
                question_id=cell.question_id,
                user_question=USER_QUESTIONS[cell.question_id],
                context=context,
                seeds=hits,
                jev=jev,
                jev_model=jev_model,
                timeout_seconds=jev_timeout_seconds,
                retrieve_seconds=0.0,
                retrieval=retrieval,
                variant=arm,
            )
            if result.notes.startswith("invalid_answer") or result.notes.startswith("invalid_decision"):
                errors.append(
                    {
                        "arm": arm,
                        "question_id": cell.question_id,
                        "relative_path": cell.relative_path,
                        "notes": result.notes,
                    }
                )
            results.append(AnswerArm(arm=arm, cell=cell, result=result, relevant_keys=relevant))
    scored = [_score_answer(item) for item in results]
    summary = _summary(scored)
    paired = _paired(scored)
    status = "blocked" if errors else "completed"
    return {
        "operation": "bm25_answer_test",
        "status": status,
        "measurement_status": status,
        "claim_scope": "improved_retrieval_only" if status != "completed" else "answer_test_run",
        "profile": profile_name,
        "top_k": TOP_K,
        "same_prompt": "P0",
        "same_answer_cell": True,
        "no_new_retrieval": True,
        "no_classify": True,
        "no_prompt_batching": True,
        "cells": len(rows),
        "scored": scored,
        "summary": summary,
        "paired": paired,
        "api_errors": errors,
        "blocked_reason": "jev_api_error" if errors else None,
    }


def candidate_lists_from_payload(
    payload: dict[str, object],
    *,
    profile: str | None = None,
) -> dict[tuple[str, str, str], FrozenCandidateList]:
    profile_name, profile_payload = _profile(payload, profile)
    manifest = payload.get("manifest") or {}
    snapshot = str(
        ((manifest.get("corpus") or {}).get("units_metadata") or {}).get(
            "units_hash_root"
        )
        or ""
    )
    output: dict[tuple[str, str, str], FrozenCandidateList] = {}
    for row in (profile_payload.get("document") or {}).get("rows") or []:
        question_id = str(row["question_id"])
        relative_path = str(row["relative_path"])
        for arm, arm_payload in (row.get("arms") or {}).items():
            hits = arm_payload.get("candidates") or []
            output[(question_id, relative_path, arm)] = candidate_list_from_arm(
                experiment_id="phase2-tantivy-bm25-v1",
                query_id=f"{question_id}:{relative_path}",
                query=USER_QUESTIONS[question_id],
                strategy=str(arm),
                index_snapshot_hash=snapshot,
                strategy_config={"profile": profile_name, "arm": arm, "k": TOP_K},
                hits=list(hits),
                scope="document",
            )
    return output


def _profile(
    payload: dict[str, object],
    requested: str | None,
) -> tuple[str, dict[str, object]]:
    profiles = payload.get("profiles") or {}
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeError("BM25 payload has no profiles")
    name = requested or next(iter(profiles))
    value = profiles.get(name)
    if not isinstance(value, dict):
        raise TypeError(f"BM25 profile {name!r} is missing")
    return name, value


def _hits(candidates: list[dict[str, object]], by_key: dict[str, StoredUnit]) -> list[SearchHit]:
    hits = []
    for candidate in candidates:
        unit = by_key.get(str(candidate.get("key") or ""))
        if unit is None:
            raise RuntimeError(f"frozen candidate is missing from the graph: {candidate.get('key')}")
        hits.append(
            SearchHit(
                node_id=unit.node_id,
                key=unit.key,
                score=float(candidate.get("score") or 0.0),
                rank=int(candidate.get("rank") or len(hits) + 1),
                document_id=unit.document_id,
                relative_path=unit.relative_path,
                text=unit.text,
            )
        )
    return hits


def _score_answer(item: AnswerArm) -> dict[str, object]:
    result = item.result
    validated = [source for source in result.sources if source.validated]
    cited = {source.unit_id for source in validated}
    citation_correct = bool(cited & item.relevant_keys) if item.relevant_keys else False
    positive = item.cell.positive_property is True
    negative = item.cell.positive_property is False
    if result.notes.startswith("invalid_answer") or result.notes.startswith("invalid_decision"):
        outcome = ERROR
        answer_correct = None
        citation_correct = None
    elif result.status == UNCERTAIN:
        outcome = ABSTENTION
        answer_correct = False
    elif positive:
        if result.status == ANSWERED and citation_correct:
            outcome = TRUE_ANSWER
            answer_correct = True
        elif result.status == ANSWERED:
            outcome = FALSE_ANSWER
            answer_correct = False
        else:
            outcome = MISS
            answer_correct = False
    elif negative:
        if result.status == ANSWERED and citation_correct:
            outcome = TRUE_ANSWER
            answer_correct = True
        elif result.status == ANSWERED:
            outcome = FALSE_ANSWER
            answer_correct = False
        elif result.status == NOT_FOUND:
            outcome = CORRECT_NOT_FOUND
            answer_correct = True
        else:
            outcome = ABSTENTION
            answer_correct = False
    else:
        outcome = ABSTENTION
        answer_correct = False
    return {
        "arm": item.arm,
        "question_id": item.cell.question_id,
        "relative_path": item.cell.relative_path,
        "split": item.cell.split,
        "answerability": item.cell.answerability,
        "positive_property": item.cell.positive_property,
        "status": result.status,
        "outcome": outcome,
        "answer_correct": answer_correct,
        "citation_correct": citation_correct,
        "false_answer": outcome == FALSE_ANSWER,
        "abstention": outcome == ABSTENTION,
        "error": outcome == ERROR,
        "cited_keys": sorted(cited),
        "relevant_keys": sorted(item.relevant_keys),
        "jev_calls": result.jev_calls,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "answer_seconds": result.answer_seconds,
        "notes": result.notes,
    }


def _summary(scored: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for arm in ("dense_bm25", "hybrid_current"):
        rows = [row for row in scored if row["arm"] == arm]
        out[arm] = {
            "cells": len(rows),
            "answer_correct": _mean_bool(rows, "answer_correct"),
            "citation_correct": _mean_bool(rows, "citation_correct"),
            "false_answers": sum(1 for row in rows if row["false_answer"]),
            "abstentions": sum(1 for row in rows if row["abstention"]),
            "errors": sum(1 for row in rows if row["error"]),
            "jev_calls": sum(int(row["jev_calls"] or 0) for row in rows),
            "prompt_tokens": sum(int(row["prompt_tokens"] or 0) for row in rows),
            "completion_tokens": sum(int(row["completion_tokens"] or 0) for row in rows),
        }
    return out


def _paired(scored: list[dict[str, object]]) -> dict[str, object]:
    by_arm: dict[str, dict[tuple[str, str], dict[str, object]]] = defaultdict(dict)
    for row in scored:
        by_arm[row["arm"]][(row["question_id"], row["relative_path"])] = row
    pairs = []
    for key, left in by_arm.get("dense_bm25", {}).items():
        right = by_arm.get("hybrid_current", {}).get(key)
        if right is None:
            continue
        pairs.append(
            {
                "question_id": key[0],
                "relative_path": key[1],
                "dense_bm25_correct": left["answer_correct"],
                "hybrid_current_correct": right["answer_correct"],
                "improved": bool(left["answer_correct"]) and not bool(right["answer_correct"]),
                "regressed": bool(right["answer_correct"]) and not bool(left["answer_correct"]),
            }
        )
    return {
        "pairs": len(pairs),
        "improved": sum(1 for row in pairs if row["improved"]),
        "regressed": sum(1 for row in pairs if row["regressed"]),
        "rows": pairs,
    }


def _mean_bool(rows: list[dict[str, object]], field: str) -> float | None:
    values = [row[field] for row in rows if row[field] is not None]
    return mean(float(value) for value in values) if values else None
