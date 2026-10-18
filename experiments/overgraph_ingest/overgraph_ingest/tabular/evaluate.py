"""Tabular Review metrics. Answer correctness is not citation correctness."""

from __future__ import annotations

from collections import defaultdict

from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN, CellResult

TRUE_ANSWER = "true_answer"
FALSE_ANSWER = "false_answer"
MISS = "miss"
CORRECT_NOT_FOUND = "correct_not_found"
ABSTENTION = "abstention"


def score_cell(result: CellResult, relevant_keys: set[str]) -> dict[str, object]:
    gold_positive = bool(relevant_keys)
    validated = [item for item in result.sources if item.validated]
    gold_cited = [item for item in validated if item.unit_id in relevant_keys]
    citation_grounded = bool(validated)
    citation_relevant = bool(gold_cited)
    answer_correct = (result.status == ANSWERED and gold_positive) or (
        result.status == NOT_FOUND and not gold_positive
    )
    if result.status == ANSWERED:
        if gold_positive and citation_relevant:
            outcome = TRUE_ANSWER
        else:
            outcome = FALSE_ANSWER
        full_success = outcome == TRUE_ANSWER
    elif result.status == UNCERTAIN:
        outcome = ABSTENTION
        full_success = False
    elif result.status == NOT_FOUND:
        outcome = CORRECT_NOT_FOUND if not gold_positive else MISS
        full_success = outcome == CORRECT_NOT_FOUND
    else:
        raise ValueError(f"unsupported cell status: {result.status}")
    hops = list(result.navigation)
    fetched = [str(hop.get("fetched")) for hop in hops if hop.get("status") == "FETCHED"]
    hop_success = len(fetched)
    hop_fail = sum(1 for hop in hops if hop.get("status") != "FETCHED")
    requested = bool(hops) or result.navigation_steps > 0
    candidates = {str(key) for key in (result.retrieval.get("candidate_keys") or [])}
    return {
        "document_id": result.document_id,
        "relative_path": result.relative_path,
        "question_id": result.question_id,
        "variant": result.variant,
        "status": result.status,
        "outcome": outcome,
        "full_success": full_success,
        "answer_correct": answer_correct,
        "citation_grounded": citation_grounded,
        "citation_relevant": citation_relevant,
        "gold_positive": gold_positive,
        "citation_accurate": citation_relevant,
        "grounded_gold": citation_relevant,
        "budget_exhausted": result.budget_exhausted,
        "navigation_steps": result.navigation_steps,
        "requested_navigation": requested,
        "answered_directly": result.variant == "A" and not requested,
        "seed_has_gold": bool(candidates & relevant_keys),
        "fetched_relevant": bool(set(fetched) & relevant_keys),
        "wrong_path": requested and gold_positive and not bool(set(fetched) & relevant_keys),
        "navigation_successes": hop_success,
        "navigation_failures": hop_fail,
        "recall@3": result.retrieval.get("recall@3"),
        "recall@5": result.retrieval.get("recall@5"),
        "recall@10": result.retrieval.get("recall@10"),
        "jev_calls": result.jev_calls,
        "cerebras_calls": result.cerebras_calls,
        "cell_seconds": result.cell_seconds,
        "retrieve_seconds": result.retrieve_seconds,
        "classify_seconds": result.classify_seconds,
        "navigate_seconds": result.navigate_seconds,
        "answer_seconds": result.answer_seconds,
        "notes": result.notes,
    }


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    n = len(rows)
    if n == 0:
        raise ValueError("no scored cells")
    counts = defaultdict(int)
    for row in rows:
        counts[str(row["outcome"])] += 1
        counts[f"status:{row['status']}"] += 1
    answered = [row for row in rows if row["status"] == ANSWERED]
    gold_pos = [row for row in rows if row["gold_positive"]]
    hops = sum(int(row["navigation_successes"]) + int(row["navigation_failures"]) for row in rows)
    hop_ok = sum(int(row["navigation_successes"]) for row in rows)
    by_question: dict[str, dict[str, object]] = {}
    for row in rows:
        bucket = by_question.setdefault(
            str(row["question_id"]),
            defaultdict(int),
        )
        bucket[str(row["outcome"])] += 1
        bucket["answer_correct"] += int(bool(row["answer_correct"]))
        bucket["citation_relevant"] += int(bool(row["citation_relevant"]))
        bucket["cells"] += 1
    return {
        "cells": n,
        "cell_accuracy": (counts[TRUE_ANSWER] + counts[CORRECT_NOT_FOUND]) / n,
        "answer_accuracy": sum(1 for row in rows if row["answer_correct"]) / n,
        "answer_coverage": len(answered) / n,
        "false_answer_rate": counts[FALSE_ANSWER] / n,
        "citation_accuracy": (
            sum(1 for row in answered if row["citation_relevant"]) / len(answered)
            if answered
            else 0.0
        ),
        "citation_grounded_rate": (
            sum(1 for row in answered if row["citation_grounded"]) / len(answered)
            if answered
            else 0.0
        ),
        "abstention_rate": counts[ABSTENTION] / n,
        "retrieval_recall@3": _mean([float(row["recall@3"] or 0.0) for row in gold_pos]),
        "retrieval_recall@5": _mean([float(row["recall@5"] or 0.0) for row in gold_pos]),
        "retrieval_recall@10": _mean([float(row["recall@10"] or 0.0) for row in gold_pos]),
        "navigation_success": (hop_ok / hops) if hops else 0.0,
        "outcomes": {
            TRUE_ANSWER: counts[TRUE_ANSWER],
            FALSE_ANSWER: counts[FALSE_ANSWER],
            MISS: counts[MISS],
            CORRECT_NOT_FOUND: counts[CORRECT_NOT_FOUND],
            ABSTENTION: counts[ABSTENTION],
        },
        "by_question": {key: dict(value) for key, value in by_question.items()},
        "latency": _latency(rows),
        "jev_calls": sum(int(row["jev_calls"]) for row in rows),
        "cerebras_calls": sum(int(row["cerebras_calls"]) for row in rows),
    }


def compare_variants(scored: list[dict[str, object]]) -> dict[str, object]:
    by_variant: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in scored:
        by_variant[str(row["variant"])].append(row)
    summaries = {variant: summarize(rows) for variant, rows in sorted(by_variant.items())}
    paired = _paired(by_variant.get("A") or [], by_variant.get("B") or [])
    navigation = _navigation(by_variant.get("A") or [], paired)
    a_acc = summaries.get("A", {}).get("cell_accuracy")
    b_acc = summaries.get("B", {}).get("cell_accuracy")
    c_acc = summaries.get("C", {}).get("cell_accuracy")
    return {
        "variants": summaries,
        "answer_improvement_a_vs_b": None if a_acc is None or b_acc is None else a_acc - b_acc,
        "answer_improvement_a_vs_c": None if a_acc is None or c_acc is None else a_acc - c_acc,
        "answer_accuracy_a_vs_b": _delta(summaries, "A", "B", "answer_accuracy"),
        "citation_accuracy_a_vs_b": _delta(summaries, "A", "B", "citation_accuracy"),
        "citation_accuracy_a_vs_c": _delta(summaries, "A", "C", "citation_accuracy"),
        "navigation": navigation,
        "paired_a_vs_b": paired["summary"],
    }


def headline(comparison: dict[str, object], cost: dict[str, object]) -> dict[str, object]:
    variants = comparison.get("variants") or {}
    return {
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "cell_accuracy": {
            name: (row or {}).get("cell_accuracy") for name, row in variants.items()
        },
        "answer_accuracy": {
            name: (row or {}).get("answer_accuracy") for name, row in variants.items()
        },
        "citation_accuracy": {
            name: (row or {}).get("citation_accuracy") for name, row in variants.items()
        },
        "citation_grounded_rate": {
            name: (row or {}).get("citation_grounded_rate") for name, row in variants.items()
        },
        "a_vs_b_cell_accuracy": comparison.get("answer_improvement_a_vs_b"),
        "a_vs_c_cell_accuracy": comparison.get("answer_improvement_a_vs_c"),
        "seconds_per_cell": {
            name: ((row or {}).get("latency") or {}).get("cell_seconds")
            for name, row in variants.items()
        },
        "cost_per_100_cells_usd": cost.get("per_100_cells_usd"),
        "jev_usd_unknown": cost.get("jev_cost_unknown"),
        "navigation": comparison.get("navigation"),
    }


def error_examples(
    cells: list[CellResult],
    scored: list[dict[str, object]],
) -> dict[str, object]:
    by_key = {
        (row["variant"], row["relative_path"], row["question_id"]): row for row in scored
    }
    picked: dict[str, dict[str, object]] = {}
    wanted = {
        "correct_answer": TRUE_ANSWER,
        "false_answer": FALSE_ANSWER,
        "missed_relevant": MISS,
        "correct_uncertain": ABSTENTION,
    }
    for cell in cells:
        row = by_key[(cell.variant, cell.relative_path, cell.question_id)]
        for label, outcome in wanted.items():
            if label in picked:
                continue
            if row["outcome"] != outcome:
                continue
            picked[label] = _example(cell, row)
        if (
            "cited_but_wrong_answer" not in picked
            and row["citation_relevant"]
            and not row["answer_correct"]
        ):
            picked["cited_but_wrong_answer"] = _example(cell, row)
        if (
            "answered_without_relevant_citation" not in picked
            and cell.status == ANSWERED
            and row["answer_correct"]
            and not row["citation_relevant"]
        ):
            picked["answered_without_relevant_citation"] = _example(cell, row)
        if "bad_citation" not in picked and cell.status == ANSWERED and not row["citation_grounded"]:
            picked["bad_citation"] = _example(cell, row)
        hops = cell.navigation
        if "successful_navigation" not in picked and any(
            hop.get("status") == "FETCHED" for hop in hops
        ):
            picked["successful_navigation"] = _example(cell, row)
        if (
            "useless_navigation" not in picked
            and hops
            and cell.navigation_steps
            and row["outcome"] != TRUE_ANSWER
        ):
            picked["useless_navigation"] = _example(cell, row)
        if "wrong_path" not in picked and row.get("wrong_path"):
            picked["wrong_path"] = _example(cell, row)
        if (
            cell.question_id == "liability-secrecy-carveout"
            and "carveout" not in picked
            and cell.status == ANSWERED
        ):
            picked["carveout"] = _example(cell, row)
    return picked


def _paired(
    variant_a: list[dict[str, object]],
    variant_b: list[dict[str, object]],
) -> dict[str, object]:
    by_b = {(row["relative_path"], row["question_id"]): row for row in variant_b}
    rows: list[dict[str, object]] = []
    for left in variant_a:
        right = by_b.get((left["relative_path"], left["question_id"]))
        if right is None:
            continue
        navigated = bool(left["requested_navigation"])
        rows.append(
            {
                "relative_path": left["relative_path"],
                "question_id": left["question_id"],
                "navigated": navigated,
                "a_full": bool(left["full_success"]),
                "b_full": bool(right["full_success"]),
                "a_answer": bool(left["answer_correct"]),
                "b_answer": bool(right["answer_correct"]),
                "improved": navigated and bool(left["full_success"]) and not bool(right["full_success"]),
                "unnecessary": navigated and bool(right["full_success"]),
                "wrong_path": bool(left["wrong_path"]),
            }
        )
    n = len(rows)
    return {
        "rows": rows,
        "summary": {
            "pairs": n,
            "answered_directly": sum(1 for row in rows if not row["navigated"]),
            "requested_navigation": sum(1 for row in rows if row["navigated"]),
            "navigation_improved": sum(1 for row in rows if row["improved"]),
            "unnecessary_navigation": sum(1 for row in rows if row["unnecessary"]),
            "wrong_path": sum(1 for row in rows if row["wrong_path"]),
            "answered_directly_rate": _ratio(rows, lambda row: not row["navigated"]),
            "requested_navigation_rate": _ratio(rows, lambda row: bool(row["navigated"])),
            "navigation_improved_rate": _ratio(
                [row for row in rows if row["navigated"]],
                lambda row: bool(row["improved"]),
            ),
            "unnecessary_navigation_rate": _ratio(
                [row for row in rows if row["navigated"]],
                lambda row: bool(row["unnecessary"]),
            ),
            "wrong_path_rate": _ratio(
                [row for row in rows if row["navigated"]],
                lambda row: bool(row["wrong_path"]),
            ),
        },
    }


def _navigation(
    variant_a: list[dict[str, object]],
    paired: dict[str, object],
) -> dict[str, object]:
    summary = dict(paired["summary"])
    hops = sum(int(row["navigation_successes"]) + int(row["navigation_failures"]) for row in variant_a)
    hop_ok = sum(int(row["navigation_successes"]) for row in variant_a)
    summary["hop_attempts"] = hops
    summary["hop_fetched"] = hop_ok
    summary["navigation_success"] = (hop_ok / hops) if hops else 0.0
    return summary


def _example(cell: CellResult, row: dict[str, object]) -> dict[str, object]:
    return {
        "variant": cell.variant,
        "document_id": cell.document_id,
        "question_id": cell.question_id,
        "status": cell.status,
        "answer": cell.answer,
        "outcome": row["outcome"],
        "answer_correct": row["answer_correct"],
        "citation_relevant": row["citation_relevant"],
        "citation_grounded": row["citation_grounded"],
        "notes": cell.notes,
        "source_unit_ids": cell.source_unit_ids,
        "navigation": cell.navigation,
    }


def _latency(rows: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    names = (
        "retrieve_seconds",
        "classify_seconds",
        "navigate_seconds",
        "answer_seconds",
        "cell_seconds",
    )
    return {name: _stats([float(row[name]) for row in rows]) for name in names}


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "mean": _mean(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
    }


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (percentile / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _ratio(rows: list[dict[str, object]], predicate) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if predicate(row)) / len(rows)


def _delta(
    summaries: dict[str, dict[str, object]],
    left: str,
    right: str,
    field: str,
) -> float | None:
    if left not in summaries or right not in summaries:
        return None
    return float(summaries[left][field]) - float(summaries[right][field])
