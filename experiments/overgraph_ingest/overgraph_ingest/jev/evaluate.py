"""Classification metrics. UNCERTAIN is counted, never treated as a silent drop."""

from __future__ import annotations

from collections import Counter

from overgraph_ingest.jev.candidates import ClassifiedCandidate
from overgraph_ingest.jev.classify import Judgment
from overgraph_ingest.retrieval.gold import RetrievalGold

WATCHED_PREFIXES = (
    "Avtal_02_",
    "Avtal_15_",
    "Avtal_18_",
    "Avtal_23_",
)

CONFIDENCE_THRESHOLDS = (0.5, 0.7, 0.9, 0.95)


def evaluate_judgments(judgments: list[Judgment]) -> dict[str, object]:
    relevant = [item for item in judgments if item.expected == "YES"]
    predicted_yes = [item for item in judgments if item.predicted == "YES"]
    true_yes = [item for item in predicted_yes if item.expected == "YES"]
    false_yes = [item for item in predicted_yes if item.expected == "NO"]
    false_no = [item for item in relevant if item.predicted == "NO"]
    uncertain = [item for item in judgments if item.predicted == "UNCERTAIN"]
    uncertain_relevant = [item for item in uncertain if item.expected == "YES"]
    counts = Counter(item.predicted for item in judgments)
    relevant_docs = {item.relative_path for item in relevant}
    yes_docs = {item.relative_path for item in true_yes}
    return {
        "candidates": len(judgments),
        "relevant_in_candidates": len(relevant),
        "predicted": dict(counts),
        "precision": (len(true_yes) / len(predicted_yes)) if predicted_yes else 0.0,
        "recall": (len(true_yes) / len(relevant)) if relevant else 0.0,
        "false_positives": [_row(item) for item in false_yes],
        "false_negatives": [_row(item) for item in false_no],
        "uncertain": [_row(item) for item in uncertain],
        "uncertain_relevant": [_row(item) for item in uncertain_relevant],
        "watch_predicted_yes": [
            _row(item)
            for item in predicted_yes
            if item.gold_label in {"hard_negative", "watch_negative"}
        ],
        "model_calls": len({item.call_index for item in judgments}),
        "errors": sum(1 for item in judgments if item.error),
        "mean_confidence": _mean(
            [item.confidence for item in judgments if item.confidence is not None]
        ),
        "document_recall": (len(yes_docs) / len(relevant_docs)) if relevant_docs else 0.0,
        "documents_found": len(yes_docs),
        "documents_expected": len(relevant_docs),
        "hard_negative_predictions": [
            _row(item)
            for item in judgments
            if item.gold_label in {"hard_negative", "watch_negative"}
        ],
        "wall_judgments": [_row(item) for item in judgments],
    }


def _row(item: Judgment) -> dict[str, object]:
    return {
        "key": item.key,
        "rank": item.rank,
        "relative_path": item.relative_path,
        "gold_label": item.gold_label,
        "expected": item.expected,
        "predicted": item.predicted,
        "confidence": item.confidence,
        "latency_ms": item.latency_ms,
        "call_index": item.call_index,
        "batch_size": item.batch_size,
        "error": item.error,
        "text": item.text[:240],
    }


def analyze_coverage_groups(
    gold: RetrievalGold,
    candidates: list[ClassifiedCandidate],
    judgments: list[Judgment],
) -> dict[str, object]:
    by_key = {item.key: item for item in judgments}
    groups = []
    for group in gold.coverage_groups:
        members = []
        for snippet in group.contains:
            match = next(
                (
                    item
                    for item in candidates
                    if item.relative_path == group.relative_path and snippet in item.text
                ),
                None,
            )
            if match is None:
                members.append(
                    {
                        "snippet": snippet,
                        "in_top_k": False,
                        "rank": None,
                        "predicted": None,
                        "confidence": None,
                    }
                )
                continue
            judged = by_key.get(match.key)
            sibling = next(
                (
                    other
                    for other in group.contains
                    if other != snippet and (other in match.previous_text or other in match.next_text)
                ),
                None,
            )
            members.append(
                {
                    "snippet": snippet,
                    "in_top_k": True,
                    "rank": match.rank,
                    "key": match.key,
                    "predicted": None if judged is None else judged.predicted,
                    "confidence": None if judged is None else judged.confidence,
                    "neighbor_has_other_span": sibling is not None,
                }
            )
        found = sum(1 for item in members if item["in_top_k"])
        ranks = [int(item["rank"]) for item in members if item["rank"] is not None]
        if found == 0:
            graph_note = "Neither supporting unit is in the candidate list; retrieval must improve first."
        elif found < len(group.contains):
            graph_note = (
                "One supporting unit is present. A neighbor hop could fetch the missing sibling; "
                "do not relabel the found unit from the missing one."
            )
        elif any(item.get("predicted") == "UNCERTAIN" for item in members):
            graph_note = (
                "Both units are present and at least one is UNCERTAIN. "
                "Combination is a separate evidence-assembly problem, not classify."
            )
        else:
            graph_note = (
                "Both units are present and classified in isolation. "
                "Combining them is a later operation."
            )
        groups.append(
            {
                "relative_path": group.relative_path,
                "found": found,
                "needed": len(group.contains),
                "both_in_top_k": found == len(group.contains),
                "rank_gap": (max(ranks) - min(ranks)) if len(ranks) > 1 else None,
                "members": members,
                "graph_note": graph_note,
            }
        )
    return {"groups": groups}


def compare_judgments(
    baseline: list[dict[str, object]],
    current: list[Judgment],
) -> dict[str, object]:
    previous = {str(row["key"]): row for row in baseline}
    changed: list[dict[str, object]] = []
    improvements: list[dict[str, object]] = []
    regressions: list[dict[str, object]] = []
    retained_true_yes = 0
    for item in current:
        before = previous.get(item.key)
        if before is None:
            continue
        before_predicted = str(before["predicted"])
        before_expected = str(before["expected"])
        before_correct = before_predicted == before_expected
        after_correct = item.predicted == item.expected
        if before_predicted == "YES" and before_expected == "YES" and item.predicted == "YES":
            retained_true_yes += 1
        if before_predicted == item.predicted:
            continue
        row = {
            "key": item.key,
            "rank": item.rank,
            "relative_path": item.relative_path,
            "gold_label": item.gold_label,
            "expected": item.expected,
            "from": before_predicted,
            "to": item.predicted,
            "from_confidence": before.get("confidence"),
            "to_confidence": item.confidence,
        }
        changed.append(row)
        if after_correct and not before_correct:
            improvements.append(row)
        elif before_correct and not after_correct:
            regressions.append(row)
    return {
        "compared": sum(1 for item in current if item.key in previous),
        "changed": changed,
        "improvements": improvements,
        "regressions": regressions,
        "unchanged": sum(
            1
            for item in current
            if item.key in previous and str(previous[item.key]["predicted"]) == item.predicted
        ),
        "retained_true_yes": retained_true_yes,
        "watched": [
            {
                "key": item.key,
                "relative_path": item.relative_path,
                "gold_label": item.gold_label,
                "expected": item.expected,
                "from": previous[item.key]["predicted"],
                "to": item.predicted,
                "from_confidence": previous[item.key].get("confidence"),
                "to_confidence": item.confidence,
            }
            for item in current
            if item.key in previous
            and any(item.relative_path.startswith(prefix) for prefix in WATCHED_PREFIXES)
        ],
    }


def threshold_stability(
    runs: list[list[dict[str, object]]],
    thresholds: tuple[float, ...] = CONFIDENCE_THRESHOLDS,
) -> dict[str, object]:
    if not runs or not runs[0]:
        return {}
    keys = [str(row["key"]) for row in runs[0]]
    by_threshold: dict[str, object] = {}
    for threshold in thresholds:
        above_sets = [_above(run, threshold) for run in runs]
        below_sets = [set(keys) - above for above in above_sets]
        unstable = [
            key
            for key in keys
            if any(key in item for item in above_sets) and any(key not in item for item in above_sets)
        ]
        by_threshold[str(threshold)] = {
            "above_in_all_runs": len(set.intersection(*above_sets)) if above_sets else 0,
            "above_in_any_run": len(set.union(*above_sets)) if above_sets else 0,
            "below_in_all_runs": len(set.intersection(*below_sets)) if below_sets else 0,
            "unstable": len(unstable),
        }
    return {
        "runs": len(runs),
        "candidates": len(keys),
        "thresholds": by_threshold,
    }


def _above(run: list[dict[str, object]], threshold: float) -> set[str]:
    keys: set[str] = set()
    for row in run:
        confidence = row.get("confidence")
        if confidence is None:
            continue
        if float(confidence) >= threshold:
            keys.add(str(row["key"]))
    return keys


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
