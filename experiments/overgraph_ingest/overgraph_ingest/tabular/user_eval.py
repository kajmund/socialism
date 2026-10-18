"""Score frozen Tabular cells against question-oriented gold. No Jev."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from overgraph_ingest.retrieval.conclusions import (
    load_tabular_dense_baseline,
    load_tabular_direct_baseline,
    load_tabular_k10_baseline,
)
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.evaluate import (
    ABSTENTION,
    CORRECT_NOT_FOUND,
    FALSE_ANSWER,
    MISS,
    TRUE_ANSWER,
)
from overgraph_ingest.tabular.gold import QUESTION_IDS, SELECTED_DOCUMENTS, USER_QUESTIONS
from overgraph_ingest.tabular.user_gold import (
    QUESTION_CONTRACTS,
    SILENT,
    TABULAR_USER_GOLD_ID,
    USER_CELLS,
    UserCellGold,
    assert_user_gold_complete,
    user_cell_map,
)

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
USER_EVAL_ID = "phase2-tabular-user-gold-v1"
USER_EVAL_PATH = ROOT / "baselines" / f"{USER_EVAL_ID}.json"
SPACE = re.compile(r"\s+")

VARIANT_SOURCES = {
    "D": load_tabular_direct_baseline,
    "E": load_tabular_dense_baseline,
    "K": load_tabular_k10_baseline,
}
HISTORICAL_CELL_KEY = {
    "D": "direct_cell_accuracy",
    "E": "dense_cell_accuracy",
    "K": "k10_cell_accuracy",
}
HISTORICAL_CITATION_KEY = {
    "D": "direct_citation_accuracy",
    "E": "dense_citation_accuracy",
    "K": "k10_citation_accuracy",
}


def normalize(text: str) -> str:
    return SPACE.sub(" ", text).strip()


def cell_text(cell: dict[str, object]) -> str:
    parts = [str(cell.get("answer") or "")]
    for source in cell.get("sources") or []:
        if isinstance(source, dict):
            parts.append(str(source.get("excerpt") or ""))
    return normalize("\n".join(parts))


def matched_spans(cell: dict[str, object], gold: UserCellGold) -> list[str]:
    text = cell_text(cell)
    hits = []
    for span in gold.answers:
        needle = normalize(span.contains)
        if needle and needle in text:
            hits.append(span.contains)
    return hits


def score_user_cell(cell: dict[str, object], gold: UserCellGold) -> dict[str, object]:
    status = str(cell.get("status") or "")
    hits = matched_spans(cell, gold)
    expect_span = bool(gold.answers)
    if status == UNCERTAIN:
        outcome = ABSTENTION
    elif status == ANSWERED:
        outcome = TRUE_ANSWER if hits else FALSE_ANSWER
    elif status == NOT_FOUND:
        if expect_span:
            outcome = MISS
        else:
            outcome = CORRECT_NOT_FOUND
    else:
        raise ValueError(f"unsupported cell status: {status}")
    return {
        "document_id": cell.get("document_id"),
        "relative_path": gold.relative_path,
        "question_id": gold.question_id,
        "user_question": USER_QUESTIONS[gold.question_id],
        "variant": cell.get("variant"),
        "status": status,
        "polarity": gold.polarity,
        "addresses": gold.addresses,
        "outcome": outcome,
        "full_success": outcome in {TRUE_ANSWER, CORRECT_NOT_FOUND},
        "matched_spans": hits,
        "gold_notes": gold.notes,
    }


def summarize_user_scores(rows: list[dict[str, object]]) -> dict[str, object]:
    n = len(rows)
    counts: dict[str, int] = defaultdict(int)
    by_question: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        outcome = str(row["outcome"])
        counts[outcome] += 1
        by_question[str(row["question_id"])][outcome] += 1
        if row.get("full_success"):
            counts["full_success"] += 1
    return {
        "cells": n,
        "full_success": counts["full_success"],
        "full_success_rate": counts["full_success"] / n if n else 0.0,
        "true_answer": counts[TRUE_ANSWER],
        "false_answer": counts[FALSE_ANSWER],
        "miss": counts[MISS],
        "correct_not_found": counts[CORRECT_NOT_FOUND],
        "abstention": counts[ABSTENTION],
        "by_question": {
            question_id: dict(by_question[question_id]) for question_id in QUESTION_IDS
        },
        "polarity": polarity_split(rows),
    }


def polarity_split(rows: list[dict[str, object]]) -> dict[str, object]:
    positive = [row for row in rows if str(row.get("polarity")) != SILENT]
    negative = [row for row in rows if str(row.get("polarity")) == SILENT]
    return {
        "positive_cells": len(positive),
        "negative_cells": len(negative),
        "positive_correct": _count(positive, full=True),
        "positive_correct_rate": _rate(positive, full=True),
        "positive_true_answer": _count(positive, TRUE_ANSWER),
        "positive_false_answer": _count(positive, FALSE_ANSWER),
        "positive_miss": _count(positive, MISS),
        "positive_abstention": _count(positive, ABSTENTION),
        "negative_stayed_negative": _count(negative, CORRECT_NOT_FOUND),
        "negative_stayed_rate": _rate(negative, CORRECT_NOT_FOUND),
        "negative_false_answer": _count(negative, FALSE_ANSWER),
        "negative_abstention": _count(negative, ABSTENTION),
    }


def _count(
    rows: list[dict[str, object]],
    outcome: str | None = None,
    *,
    full: bool = False,
) -> int:
    if full:
        return sum(1 for row in rows if row.get("full_success"))
    return sum(1 for row in rows if row.get("outcome") == outcome)


def _rate(
    rows: list[dict[str, object]],
    outcome: str | None = None,
    *,
    full: bool = False,
) -> float:
    if not rows:
        return 0.0
    return _count(rows, outcome, full=full) / len(rows)


def _cells_from_baseline(payload: dict[str, object]) -> list[dict[str, object]]:
    cells = payload.get("cells")
    if isinstance(cells, list) and cells:
        return [cell for cell in cells if isinstance(cell, dict)]
    rows = payload.get("results") or payload.get("observations") or []
    if isinstance(rows, list):
        found = [row for row in rows if isinstance(row, dict) and "status" in row]
        if found:
            return found
    raise ValueError("frozen baseline has no cells")


def score_frozen_variant(variant: str) -> dict[str, object]:
    loader = VARIANT_SOURCES[variant]
    cells = _cells_from_baseline(loader())
    golds = user_cell_map()
    rows = []
    for cell in cells:
        path = str(cell.get("relative_path") or "")
        question_id = str(cell.get("question_id") or "")
        gold = golds[(path, question_id)]
        rows.append(score_user_cell(cell, gold))
    if len(rows) != len(golds):
        raise ValueError(f"{variant} cell count {len(rows)} != gold {len(golds)}")
    return {
        "variant": variant,
        "summary": summarize_user_scores(rows),
        "rows": rows,
    }


def historical_passage_gold() -> dict[str, dict[str, float]]:
    rates = {}
    for name, loader in VARIANT_SOURCES.items():
        headline = loader().get("headline") or {}
        rates[name] = {
            "cell_accuracy": float(headline[HISTORICAL_CELL_KEY[name]]),
            "citation_accuracy": float(headline[HISTORICAL_CITATION_KEY[name]]),
        }
    return rates


def compare_user_gold() -> dict[str, object]:
    assert_user_gold_complete()
    variants = {name: score_frozen_variant(name) for name in VARIANT_SOURCES}
    historical = historical_passage_gold()
    user_rates = {
        name: payload["summary"]["full_success_rate"] for name, payload in variants.items()
    }
    return {
        "operation": "tabular_user_gold",
        "experiment": USER_EVAL_ID,
        "gold_id": TABULAR_USER_GOLD_ID,
        "does_not_change_retrieval_gold": True,
        "does_not_change_user_questions": True,
        "does_not_change_default_prompt": True,
        "does_not_run_jev": True,
        "do_not_retune_gold_to_model": True,
        "historical_cell_accuracy_is_not_user_quality": True,
        "user_question_is_the_contract": True,
        "cells": len(USER_CELLS),
        "documents": list(SELECTED_DOCUMENTS),
        "historical_passage_gold": historical,
        "variants": {
            name: {
                "variant": name,
                "summary": payload["summary"],
                "rows": payload["rows"],
            }
            for name, payload in variants.items()
        },
        "headline": user_rates,
        "ranking_flipped": (
            historical["D"]["cell_accuracy"] >= historical["E"]["cell_accuracy"]
            and user_rates["E"] > user_rates["D"]
        ),
    }


def freeze_user_gold(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": USER_EVAL_ID,
        "label": (
            "Question-oriented Tabular Review gold, scored against frozen D, E, and K. "
            "No new Jev run. Retrieval gold and P0 are unchanged."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_change_retrieval_gold": True,
        "does_not_run_jev": True,
        "do_not_retune_gold_to_model": True,
        "historical_cell_accuracy_is_not_user_quality": True,
        "user_question_is_the_contract": True,
        "gold_id": payload.get("gold_id"),
        "headline": payload.get("headline"),
        "historical_passage_gold": payload.get("historical_passage_gold"),
        "ranking_flipped": payload.get("ranking_flipped"),
        "variants": {
            name: variant["summary"] for name, variant in payload["variants"].items()
        },
        "rows": {
            name: variant["rows"] for name, variant in payload["variants"].items()
        },
    }


def write_user_gold_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or USER_EVAL_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_user_gold(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_user_gold_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "user-gold-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Tabular Review user gold",
        "",
        "The user question is the contract.",
        "Retrieval gold, user questions, and P0 are unchanged.",
        "No new Jev run. Frozen D, E, and K are rescored offline.",
        "Historical 78% / 54% remain passage-gold benchmarks only.",
        "",
        "## What each question means",
        "",
    ]
    for question_id in QUESTION_IDS:
        contract = QUESTION_CONTRACTS[question_id]
        lines.extend(
            [
                f"### {question_id}",
                "",
                f"Asked: {contract['question']}",
                "",
                contract["asks"],
                "",
                contract["not_the_old_gold"],
                "",
            ]
        )
    historical = payload["historical_passage_gold"]
    lines.extend(
        [
            "## Frozen variants against this gold",
            "",
            "78% and 54% stay as passage-gold history. They are not",
            "user-question quality.",
            "",
            "| Variant | Passage gold | User gold | True | False | Miss | Empty | Uncertain |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name in ("D", "E", "K"):
        summary = payload["variants"][name]["summary"]
        old = historical[name]
        lines.append(
            "| {name} | {old:.0%} | {rate:.0%} ({ok}/{n}) | {true_answer} | "
            "{false_answer} | {miss} | {correct_not_found} | {abstention} |".format(
                name=name,
                old=old["cell_accuracy"],
                rate=summary["full_success_rate"],
                ok=summary["full_success"],
                n=summary["cells"],
                **summary,
            )
        )
    if payload.get("ranking_flipped"):
        lines.extend(
            [
                "",
                "Against passage gold D beat E and K. Against the user",
                "question E and K beat D. D still misses several operative",
                "secrecy duties that were never in retrieval gold.",
            ]
        )
    lines.extend(["", "## By question (D)", "", "| Question | True | False | Miss | Empty | Uncertain |", "|---|---:|---:|---:|---:|---:|"])
    for question_id in QUESTION_IDS:
        counts = payload["variants"]["D"]["summary"]["by_question"][question_id]
        lines.append(
            "| {q} | {true} | {false} | {miss} | {empty} | {abs} |".format(
                q=question_id,
                true=counts.get(TRUE_ANSWER, 0),
                false=counts.get(FALSE_ANSWER, 0),
                miss=counts.get(MISS, 0),
                empty=counts.get(CORRECT_NOT_FOUND, 0),
                abs=counts.get(ABSTENTION, 0),
            )
        )
    lines.extend(
        [
            "",
            "## What this is not",
            "",
            "- Not a rewrite of retrieval gold.",
            "- Not a new prompt or retrieval setting.",
            "- Not a reason to keep 78% as Tabular Review quality.",
            "- Not a reason to switch the default from D.",
            "- Not a reason to add special rules for vite or headings.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
