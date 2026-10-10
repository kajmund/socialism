"""Compare two Coverage v3 gold payloads. Does not retrieve or classify."""

from __future__ import annotations


def gold_row(payload: dict[str, object], gold_id: str) -> dict[str, object]:
    for item in payload.get("golds") or []:
        if item.get("gold_id") == gold_id:
            return dict(item)
    raise KeyError(gold_id)


def budget_row(gold: dict[str, object], budget: int) -> dict[str, object]:
    for row in gold.get("budgets") or []:
        if row.get("budget") == budget:
            return dict(row)
    raise KeyError(budget)


def compare_v3_golds(
    baseline: dict[str, object],
    treatment: dict[str, object],
    *,
    gold_id: str,
    budgets: tuple[int, ...] = (1, 2, 3, 5),
) -> dict[str, object]:
    left = gold_row(baseline, gold_id)
    right = gold_row(treatment, gold_id)
    rows = []
    for budget in budgets:
        base = budget_row(left, budget)
        treat = budget_row(right, budget)
        rows.append(
            {
                "budget": budget,
                "baseline": _cell(base),
                "treatment": _cell(treat),
                "delta": {
                    "classified": _sub(treat.get("classified"), base.get("classified")),
                    "jev_calls": _sub(treat.get("jev_calls"), base.get("jev_calls")),
                    "cumulative_jev_calls": _sub(
                        _cumulative(right, budget),
                        _cumulative(left, budget),
                    ),
                    "document_recall": _fsub(treat.get("document_recall"), base.get("document_recall")),
                    "jev_yes_document_recall": _fsub(
                        treat.get("jev_yes_document_recall"),
                        base.get("jev_yes_document_recall"),
                    ),
                    "budget_exhausted_documents": _sub(
                        treat.get("budget_exhausted_documents"),
                        base.get("budget_exhausted_documents"),
                    ),
                },
            }
        )
    first_complete = {
        "baseline": _first_complete(left),
        "treatment": _first_complete(right),
    }
    return {
        "gold_id": gold_id,
        "baseline_query": left.get("query"),
        "treatment_query": right.get("query_used") or right.get("query"),
        "baseline_recall_at_50": left.get("recall_at_50"),
        "treatment_recall_at_50": right.get("recall_at_50"),
        "first_complete": first_complete,
        "budgets": rows,
    }


def _cell(row: dict[str, object]) -> dict[str, object]:
    return {
        "classified": row.get("classified"),
        "jev_calls": row.get("jev_calls"),
        "cache_hits": row.get("cache_hits"),
        "document_recall": row.get("document_recall"),
        "jev_yes_document_recall": row.get("jev_yes_document_recall"),
        "budget_exhausted_documents": row.get("budget_exhausted_documents"),
        "unresolved_relevant_documents": row.get("unresolved_relevant_documents"),
        "false_negative_documents": row.get("false_negative_documents"),
        "wall_seconds": row.get("wall_seconds"),
        "status_counts": row.get("status_counts"),
    }


def _cumulative(gold: dict[str, object], budget: int) -> int:
    total = 0
    for row in gold.get("budgets") or []:
        value = row.get("budget")
        if value is None or int(value) > budget:
            continue
        total += int(row.get("jev_calls") or 0)
    return total


def _first_complete(gold: dict[str, object]) -> dict[str, object] | None:
    for row in gold.get("budgets") or []:
        if float(row.get("jev_yes_document_recall") or 0) + 1e-9 >= 1.0:
            return {
                "budget": row.get("budget"),
                "classified": row.get("classified"),
                "jev_calls": row.get("jev_calls"),
                "cumulative_jev_calls": _cumulative(gold, int(row["budget"])),
                "document_recall": row.get("document_recall"),
            }
    return None


def _sub(left, right) -> int | None:
    if left is None or right is None:
        return None
    return int(left) - int(right)


def _fsub(left, right) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)
