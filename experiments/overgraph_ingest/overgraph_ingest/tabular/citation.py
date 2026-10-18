"""Why Tabular citation accuracy is ~54%. Saved results only. No new model."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.conclusions import (
    load_tabular_qwen_baseline,
    load_tabular_review_baseline,
)
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.tabular.contract import ANSWERED
from overgraph_ingest.tabular.gold import QUESTION_IDS

ROOT = Path(__file__).resolve().parents[2]
TABULAR_CITATION_ID = "phase2-tabular-citation-v1"
TABULAR_CITATION_PATH = ROOT / "baselines" / f"{TABULAR_CITATION_ID}.json"
QUALITY_REFERENCE_VARIANT = "B"
MODEL_VARIANTS = ("B", "C", "Q")
ALL_VARIANTS = ("A", "B", "C", "Q")
OFFICIAL_GOLD_POSITIVE = 27


def gold_hit(recall: object) -> bool:
    return float(recall or 0.0) > 0.0


def classify_selection(row: dict[str, object]) -> str | None:
    if not row.get("gold_positive") or not row.get("seed_has_gold"):
        return None
    if row.get("citation_relevant"):
        return "cited_gold"
    if row.get("status") == ANSWERED:
        return "wrong_pick"
    return "no_answer"


def classify_citation_failure(row: dict[str, object]) -> str | None:
    if row.get("status") != ANSWERED or row.get("citation_relevant"):
        return None
    if not row.get("gold_positive"):
        return "gold_negative_false_answer"
    if not row.get("seed_has_gold"):
        return "missing_gold"
    return "wrong_pick"


def run_tabular_citation(
    *,
    review: dict[str, object] | None = None,
    qwen: dict[str, object] | None = None,
    expected_gold_positive: int | None = None,
) -> dict[str, object]:
    official = review is None and qwen is None
    source = review or load_tabular_review_baseline()
    extra = qwen or load_tabular_qwen_baseline()
    scored = {
        variant: _index(_rows(source, extra, "scored"), variant) for variant in ALL_VARIANTS
    }
    cells = {
        variant: _index(_rows(source, extra, "cells"), variant) for variant in ALL_VARIANTS
    }
    gold_pos = [row for row in scored[QUALITY_REFERENCE_VARIANT].values() if row["gold_positive"]]
    expected = OFFICIAL_GOLD_POSITIVE if official else expected_gold_positive
    if expected is not None and len(gold_pos) != expected:
        raise ValueError(f"gold-positive cells must be {expected}, got {len(gold_pos)}")
    retrieval = _retrieval(gold_pos)
    variants = {
        variant: _variant(scored[variant], retrieval["missing_at_k5"])
        for variant in ALL_VARIANTS
        if scored[variant]
    }
    missing = _missing_cells(gold_pos, cells[QUALITY_REFERENCE_VARIANT], scored)
    return {
        "operation": "tabular_citation",
        "experiment": "tabular_citation_v1",
        "task": "retrieval_versus_source_selection",
        "replay_of": ("phase2-tabular-review-v1", "phase2-tabular-qwen-v1"),
        "quality_reference": QUALITY_REFERENCE_VARIANT,
        "model_comparisons_paused": True,
        "no_new_model": True,
        "no_new_retrieval": True,
        "no_navigation": True,
        "applied_to_v3": False,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_qwen": True,
        "navigation_not_changed": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "k": 5,
        "gold_positive_cells": len(gold_pos),
        "retrieval": retrieval,
        "variants": variants,
        "missing_cells": missing,
        "verdict": "retrieval_not_selection",
        "next": "document_local_retrieval",
        "not_next": ("source_selection", "more_models", "navigation"),
        "headline": _headline(retrieval, variants, missing),
    }


def freeze_tabular_citation(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_CITATION_ID,
        "label": (
            "Frozen: Tabular citation accuracy is retrieval, not source "
            "selection. Jev B is the quality reference. Model comparisons "
            "are paused. Does not replace C@8, Coverage v3, tabular v1, "
            "or tabular Qwen. Does not start navigation."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_qwen": True,
        "navigation_not_changed": True,
        "model_comparisons_paused": True,
        "quality_reference": QUALITY_REFERENCE_VARIANT,
        "no_new_model": True,
        "no_new_retrieval": True,
        "same_mapping": GOLD_MAP_VERSION,
        "selection_is_diagnostic": True,
        "verdict": payload.get("verdict"),
        "next": payload.get("next"),
        "not_next": payload.get("not_next"),
        "headline": payload.get("headline"),
        "retrieval": payload.get("retrieval"),
        "variants": payload.get("variants"),
        "missing_cells": payload.get("missing_cells"),
    }


def write_tabular_citation_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_CITATION_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_citation(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _rows(
    review: dict[str, object],
    qwen: dict[str, object],
    field: str,
) -> list[dict[str, object]]:
    rows = [row for row in (review.get(field) or []) if isinstance(row, dict)]
    rows.extend(row for row in (qwen.get(field) or []) if isinstance(row, dict))
    return rows


def _index(
    rows: list[dict[str, object]],
    variant: str,
) -> dict[tuple[str, str], dict[str, object]]:
    return {
        (str(row["relative_path"]), str(row["question_id"])): row
        for row in rows
        if row.get("variant") == variant
    }


def _retrieval(gold_pos: list[dict[str, object]]) -> dict[str, object]:
    hits = {k: sum(1 for row in gold_pos if gold_hit(row.get(f"recall@{k}"))) for k in (3, 5, 10)}
    n = len(gold_pos)
    missing = [row for row in gold_pos if not row.get("seed_has_gold")]
    recoverable = [row for row in missing if gold_hit(row.get("recall@10"))]
    by_question: dict[str, dict[str, object]] = {}
    for question_id in QUESTION_IDS:
        rows = [row for row in gold_pos if row["question_id"] == question_id]
        by_question[question_id] = {
            "gold_positive": len(rows),
            "gold_hit@3": sum(1 for row in rows if gold_hit(row.get("recall@3"))),
            "gold_hit@5": sum(1 for row in rows if gold_hit(row.get("recall@5"))),
            "gold_hit@10": sum(1 for row in rows if gold_hit(row.get("recall@10"))),
            "seed_has_gold": sum(1 for row in rows if row.get("seed_has_gold")),
        }
    return {
        "cells": n,
        "gold_hit@3": _ratio(hits[3], n),
        "gold_hit@5": _ratio(hits[5], n),
        "gold_hit@10": _ratio(hits[10], n),
        "gold_hit@3_count": hits[3],
        "gold_hit@5_count": hits[5],
        "gold_hit@10_count": hits[10],
        "gold_recall@3": _mean([float(row.get("recall@3") or 0.0) for row in gold_pos]),
        "gold_recall@5": _mean([float(row.get("recall@5") or 0.0) for row in gold_pos]),
        "gold_recall@10": _mean([float(row.get("recall@10") or 0.0) for row in gold_pos]),
        "present_at_k5": n - len(missing),
        "missing_at_k5": len(missing),
        "recoverable_at_k10": len(recoverable),
        "still_missing_at_k10": len(missing) - len(recoverable),
        "missing_are_confidentiality": bool(missing)
        and all(row["question_id"] == "confidentiality" for row in missing),
        "by_question": by_question,
    }


def _variant(
    rows: dict[tuple[str, str], dict[str, object]],
    missing_at_k5: int,
) -> dict[str, object]:
    values = list(rows.values())
    answered = [row for row in values if row["status"] == ANSWERED]
    gold_pos = [row for row in values if row["gold_positive"]]
    present = [row for row in gold_pos if row.get("seed_has_gold")]
    gold_pos_answered = [row for row in gold_pos if row["status"] == ANSWERED]
    present_answered = [row for row in present if row["status"] == ANSWERED]
    selections = [classify_selection(row) for row in present]
    failures = [classify_citation_failure(row) for row in answered]
    failure_counts = defaultdict(int)
    for label in failures:
        if label is not None:
            failure_counts[label] += 1
    selection_counts = defaultdict(int)
    for label in selections:
        if label is not None:
            selection_counts[label] += 1
    gold_pos_fail = [row for row in gold_pos if not row.get("full_success")]
    return {
        "cells": len(values),
        "answered": len(answered),
        "citation_accuracy": _ratio(
            sum(1 for row in answered if row.get("citation_relevant")),
            len(answered),
        ),
        "citation_accuracy_gold_positive_answered": _ratio(
            sum(1 for row in gold_pos_answered if row.get("citation_relevant")),
            len(gold_pos_answered),
        ),
        "citation_accuracy_when_present": _ratio(
            sum(1 for row in present_answered if row.get("citation_relevant")),
            len(present_answered),
        ),
        "source_selection_when_present": _ratio(
            selection_counts["cited_gold"],
            len(present),
        ),
        "cited_gold_when_present": selection_counts["cited_gold"],
        "wrong_pick_when_present": selection_counts["wrong_pick"],
        "no_answer_when_present": selection_counts["no_answer"],
        "present_at_k5": len(present),
        "citation_failures": {
            "answered_without_gold_citation": len(answered)
            - sum(1 for row in answered if row.get("citation_relevant")),
            "gold_negative_false_answer": failure_counts["gold_negative_false_answer"],
            "missing_gold": failure_counts["missing_gold"],
            "wrong_pick": failure_counts["wrong_pick"],
        },
        "gold_positive_failures": len(gold_pos_fail),
        "gold_positive_failures_missing_gold": sum(
            1 for row in gold_pos_fail if not row.get("seed_has_gold")
        ),
        "missing_gold_errors": missing_at_k5,
    }


def _missing_cells(
    gold_pos: list[dict[str, object]],
    reference_cells: dict[tuple[str, str], dict[str, object]],
    scored: dict[str, dict[tuple[str, str], dict[str, object]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in gold_pos:
        if row.get("seed_has_gold"):
            continue
        key = (str(row["relative_path"]), str(row["question_id"]))
        cell = reference_cells.get(key) or {}
        rows.append(
            {
                "document_id": row.get("document_id") or cell.get("document_id"),
                "relative_path": row["relative_path"],
                "question_id": row["question_id"],
                "recall@3": row.get("recall@3"),
                "recall@5": row.get("recall@5"),
                "recall@10": row.get("recall@10"),
                "recoverable_at_k10": gold_hit(row.get("recall@10")),
                "statuses": {
                    variant: (scored[variant].get(key) or {}).get("status")
                    for variant in MODEL_VARIANTS
                    if scored[variant]
                },
            }
        )
    rows.sort(key=lambda item: (str(item["question_id"]), str(item["relative_path"])))
    return rows


def _headline(
    retrieval: dict[str, object],
    variants: dict[str, dict[str, object]],
    missing: list[dict[str, object]],
) -> dict[str, object]:
    reference = variants[QUALITY_REFERENCE_VARIANT]
    return {
        "selection_is_diagnostic": True,
        "selection_is_not_general_quality": True,
        "quality_reference": QUALITY_REFERENCE_VARIANT,
        "model_comparisons_paused": True,
        "verdict": "retrieval_not_selection",
        "next": "document_local_retrieval",
        "gold_positive_cells": retrieval["cells"],
        "gold_hit@3": retrieval["gold_hit@3"],
        "gold_hit@5": retrieval["gold_hit@5"],
        "gold_hit@10": retrieval["gold_hit@10"],
        "gold_recall@3": retrieval["gold_recall@3"],
        "gold_recall@5": retrieval["gold_recall@5"],
        "gold_recall@10": retrieval["gold_recall@10"],
        "source_selection_when_present": {
            variant: row["source_selection_when_present"]
            for variant, row in variants.items()
            if variant in MODEL_VARIANTS
        },
        "citation_accuracy": {
            variant: row["citation_accuracy"]
            for variant, row in variants.items()
            if variant in MODEL_VARIANTS
        },
        "citation_accuracy_when_present": {
            variant: row["citation_accuracy_when_present"]
            for variant, row in variants.items()
            if variant in MODEL_VARIANTS
        },
        "missing_gold_at_k5": retrieval["missing_at_k5"],
        "recoverable_at_k10": retrieval["recoverable_at_k10"],
        "still_missing_at_k10": retrieval["still_missing_at_k10"],
        "missing_are_confidentiality": retrieval["missing_are_confidentiality"],
        "jev_cited_gold_whenever_present": reference["wrong_pick_when_present"] == 0
        and reference["cited_gold_when_present"] == reference["present_at_k5"],
        "citation_failures_are_mostly_gold_negative": (
            reference["citation_failures"]["gold_negative_false_answer"]
            > reference["citation_failures"]["missing_gold"]
            + reference["citation_failures"]["wrong_pick"]
        ),
        "missing_documents": [row["document_id"] for row in missing],
    }


def _ratio(count: int, n: int) -> float:
    if n == 0:
        return 0.0
    return count / n


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
