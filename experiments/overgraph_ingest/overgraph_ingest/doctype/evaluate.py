"""Accuracy, per-type precision/recall, and confusion. No invented thresholds."""

from __future__ import annotations

from overgraph_ingest.doctype.taxonomy import DOCUMENT_TYPES


def score_row(predicted: str, gold: str) -> dict[str, object]:
    return {
        "predicted": predicted,
        "gold": gold,
        "correct": predicted == gold,
    }


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    correct = sum(1 for row in rows if row["correct"])
    confusion = {
        gold: {predicted: 0 for predicted in DOCUMENT_TYPES} for gold in DOCUMENT_TYPES
    }
    for row in rows:
        confusion[str(row["gold"])][str(row["predicted"])] += 1
    per_type = {
        document_type: _type_scores(rows, document_type) for document_type in DOCUMENT_TYPES
    }
    return {
        "n": len(rows),
        "correct": correct,
        "accuracy": _ratio(correct, len(rows)),
        "per_type": per_type,
        "confusion": confusion,
        "errors": [row for row in rows if not row["correct"]],
    }


def pair_variants(
    left_rows: list[dict[str, object]],
    right_rows: list[dict[str, object]],
    *,
    left_name: str,
    right_name: str,
) -> dict[str, object]:
    by_right = {str(row["relative_path"]): row for row in right_rows}
    paired = []
    for left in left_rows:
        path = str(left["relative_path"])
        right = by_right[path]
        paired.append(
            {
                "relative_path": path,
                "gold": left["gold"],
                left_name: left["predicted"],
                right_name: right["predicted"],
                "changed": left["predicted"] != right["predicted"],
                "left_correct": left["correct"],
                "right_correct": right["correct"],
                "fixed": (not left["correct"]) and right["correct"],
                "regressed": left["correct"] and not right["correct"],
            }
        )
    return {
        "n": len(paired),
        "changed": sum(1 for row in paired if row["changed"]),
        "fixed": sum(1 for row in paired if row["fixed"]),
        "regressed": sum(1 for row in paired if row["regressed"]),
        "rows": paired,
    }


def decide(
    summaries: dict[str, dict[str, object]],
    paired: dict[str, dict[str, object]],
) -> dict[str, object]:
    accuracies = {
        name: float(summary["accuracy"] or 0.0) for name, summary in summaries.items()
    }
    best = max(accuracies, key=accuracies.get)
    jev_names = [name for name in ("B", "C") if name in accuracies]
    jev_best = max((accuracies[name] for name in jev_names), default=0.0)
    a_accuracy = accuracies.get("A", 0.0)
    return {
        "best_variant": best,
        "accuracies": accuracies,
        "a_is_enough_on": summaries.get("A", {}).get("correct"),
        "jev_adds_measurable_quality": jev_best > a_accuracy,
        "wider_context_improves": accuracies.get("C", 0.0) > accuracies.get("B", 0.0),
        "no_quality_threshold": True,
        "choose_from_results": True,
        "paired": {
            name: {key: value[key] for key in ("changed", "fixed", "regressed")}
            for name, value in paired.items()
        },
        "reason": _reason(accuracies, jev_best, a_accuracy),
    }


def _type_scores(rows: list[dict[str, object]], document_type: str) -> dict[str, object]:
    gold_n = sum(1 for row in rows if row["gold"] == document_type)
    predicted_n = sum(1 for row in rows if row["predicted"] == document_type)
    true_n = sum(
        1
        for row in rows
        if row["gold"] == document_type and row["predicted"] == document_type
    )
    return {
        "gold_n": gold_n,
        "predicted_n": predicted_n,
        "true_n": true_n,
        "precision": _ratio(true_n, predicted_n),
        "recall": _ratio(true_n, gold_n),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _reason(
    accuracies: dict[str, float],
    jev_best: float,
    a_accuracy: float,
) -> str:
    ordered = ", ".join(
        f"{name} {accuracies[name]:.1%}" for name in ("A", "B", "C") if name in accuracies
    )
    if jev_best > a_accuracy:
        return (
            f"{ordered}. Jev beat the structure-only variant. "
            "Choose the method from this table. No quality threshold was set."
        )
    return (
        f"{ordered}. Jev did not beat the structure-only variant. "
        "Choose the method from this table. No quality threshold was set."
    )
