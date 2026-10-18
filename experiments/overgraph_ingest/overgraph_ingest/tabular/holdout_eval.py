"""Freeze holdout gold. Models are not run."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.tabular.gold import QUESTION_IDS, USER_QUESTIONS
from overgraph_ingest.tabular.holdout import HOLD_OUT_DOCUMENTS, HOLD_OUT_ID, HOLD_OUT_STRIDE
from overgraph_ingest.tabular.holdout_gold import HOLD_OUT_CELLS, assert_holdout_gold_complete
from overgraph_ingest.tabular.user_gold import (
    CELL_MAY_HAVE_MULTIPLE_ANSWERS,
    QUESTION_CONTRACTS,
    SILENT,
)

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
HOLD_OUT_EVAL_ID = "phase2-tabular-holdout-gold-v1"
HOLD_OUT_EVAL_PATH = ROOT / "baselines" / f"{HOLD_OUT_EVAL_ID}.json"
HOLD_OUT_VARIANTS = ("D", "E", "K")


def serialize_holdout_cells() -> list[dict[str, object]]:
    rows = []
    for cell in HOLD_OUT_CELLS:
        rows.append(
            {
                "relative_path": cell.relative_path,
                "question_id": cell.question_id,
                "user_question": USER_QUESTIONS[cell.question_id],
                "polarity": cell.polarity,
                "addresses": cell.addresses,
                "answers": [
                    {"contains": span.contains, "applies_to": span.applies_to}
                    for span in cell.answers
                ],
                "notes": cell.notes,
            }
        )
    return rows


def review_holdout_gold() -> dict[str, object]:
    assert_holdout_gold_complete()
    cells = serialize_holdout_cells()
    by_question = {question_id: 0 for question_id in QUESTION_IDS}
    polarities: dict[str, int] = {}
    for cell in HOLD_OUT_CELLS:
        polarities[cell.polarity] = polarities.get(cell.polarity, 0) + 1
        if cell.polarity != SILENT:
            by_question[cell.question_id] += 1
    return {
        "operation": "tabular_holdout_gold",
        "experiment": HOLD_OUT_EVAL_ID,
        "gold_id": HOLD_OUT_ID,
        "does_not_run_jev": True,
        "does_not_run_cerebras": True,
        "does_not_run_qwen": True,
        "does_not_change_retrieval_gold": True,
        "does_not_change_user_questions": True,
        "does_not_change_default_prompt": True,
        "does_not_change_default_hybrid": True,
        "does_not_change_default_k": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "do_not_add_special_rules": True,
        "do_not_keep_optimizing_diagnostic_20": True,
        "user_question_is_the_contract": True,
        "cell_may_have_multiple_answers": CELL_MAY_HAVE_MULTIPLE_ANSWERS,
        "models_not_run": True,
        "compare_when_models_run": list(HOLD_OUT_VARIANTS),
        "documents": list(HOLD_OUT_DOCUMENTS),
        "stride": HOLD_OUT_STRIDE,
        "cells": cells,
        "headline": {
            "documents": len(HOLD_OUT_DOCUMENTS),
            "cells": len(HOLD_OUT_CELLS),
            "addressed": sum(1 for cell in HOLD_OUT_CELLS if cell.polarity != SILENT),
            "silent": polarities.get(SILENT, 0),
            "polarities": polarities,
            "addressed_by_question": by_question,
            "models_not_run": True,
        },
    }


def freeze_holdout_gold(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": HOLD_OUT_EVAL_ID,
        "label": (
            "Independent 20-document holdout. Question gold written before "
            "any D/E/K run. Default stays hybrid k=5 / D. E is the next "
            "candidate, not the new default."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_run_jev": True,
        "models_not_run": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "do_not_add_special_rules": True,
        "user_question_is_the_contract": True,
        "cell_may_have_multiple_answers": True,
        "gold_id": payload.get("gold_id"),
        "documents": payload.get("documents"),
        "stride": payload.get("stride"),
        "headline": payload.get("headline"),
        "cells": payload.get("cells"),
        "compare_when_models_run": payload.get("compare_when_models_run"),
    }


def write_holdout_gold_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or HOLD_OUT_EVAL_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_holdout_gold(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_holdout_gold_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "holdout-gold-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    headline = payload["headline"]
    lines = [
        "# Tabular Review holdout gold",
        "",
        "Gold before models. Default stays D (hybrid k=5).",
        "E (dense k=5) is the next candidate, not the new default.",
        "No Cerebras. No Qwen. No new prompt. No special rules.",
        "A cell may list several structured answers.",
        "",
        "## Selection",
        "",
        "Twenty documents from the 66 leftovers that are neither the",
        "diagnostic twenty nor the status-v2 cases. Every third leftover",
        f"by Avtal number, stride {payload['stride']}.",
        "",
        "| Document |",
        "|---|",
    ]
    for path in payload["documents"]:
        lines.append(f"| {path} |")
    lines.extend(
        [
            "",
            f"Addressed cells: {headline['addressed']}/100. Silent: {headline['silent']}.",
            "",
            "## What each question means",
            "",
        ]
    )
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
            ]
        )
    lines.extend(
        [
            "## What this is not",
            "",
            "- Not a run of D, E, or K.",
            "- Not a default change.",
            "- Not more work on the diagnostic twenty.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def refuse_holdout_model_run() -> None:
    raise RuntimeError(
        "holdout gold is frozen; D/E/K are not run yet. "
        "Do not call Jev, Cerebras, or Qwen on these documents."
    )
