"""Freeze document-type gold. Models are not run."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.doctype.gold import (
    DOCUMENTS,
    GOLD_ID,
    HARD_CASES,
    assert_gold_complete,
    gold_by_path,
)
from overgraph_ingest.doctype.taxonomy import DOCUMENT_TYPES, TAXONOMY_VERSION, TYPE_LABELS

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
DOCTYPE_GOLD_ID = "phase2-doctype-gold-v1"
DOCTYPE_GOLD_PATH = ROOT / "baselines" / f"{DOCTYPE_GOLD_ID}.json"


def review_doctype_gold() -> dict[str, object]:
    assert_gold_complete()
    mapping = gold_by_path()
    counts = {document_type: 0 for document_type in DOCUMENT_TYPES}
    for document_type in mapping.values():
        counts[document_type] += 1
    return {
        "operation": "doctype_gold",
        "experiment": DOCTYPE_GOLD_ID,
        "gold_id": GOLD_ID,
        "taxonomy_version": TAXONOMY_VERSION,
        "does_not_run_jev": True,
        "models_not_run": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "does_not_change_default_hybrid": True,
        "default_remains_d": True,
        "principal_function_not_clauses": True,
        "no_production_integration": True,
        "documents": list(DOCUMENTS),
        "labels": [
            {
                "relative_path": path,
                "document_type": mapping[path],
                "label": TYPE_LABELS[mapping[path]],
            }
            for path in DOCUMENTS
        ],
        "hard_cases": [
            {
                "case_id": case.case_id,
                "left_path": case.left_path,
                "left_type": mapping[case.left_path],
                "right_path": case.right_path,
                "right_type": mapping[case.right_path],
                "note": case.note,
            }
            for case in HARD_CASES
        ],
        "headline": {
            "documents": len(DOCUMENTS),
            "counts": counts,
            "hard_cases": len(HARD_CASES),
            "models_not_run": True,
        },
    }


def freeze_doctype_gold(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": DOCTYPE_GOLD_ID,
        "label": (
            "Document-type gold for the 100 published contracts. "
            "Principal function only. Locked before Jev."
        ),
        "do_not_overwrite": True,
        "does_not_run_jev": True,
        "models_not_run": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "default_remains_d": True,
        "principal_function_not_clauses": True,
        "gold_id": payload.get("gold_id"),
        "taxonomy_version": payload.get("taxonomy_version"),
        "documents": payload.get("documents"),
        "headline": payload.get("headline"),
        "hard_cases": payload.get("hard_cases"),
        "labels": payload.get("labels"),
    }


def write_doctype_gold_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or DOCTYPE_GOLD_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_doctype_gold(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_doctype_gold_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "doctype-gold-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    counts = payload["headline"]["counts"]
    lines = [
        "# Document-type gold",
        "",
        "Gold before models. Principal function, not clauses.",
        "No Jev. No retrieval change. No `answer_cell` change.",
        "",
        "## Counts",
        "",
        "| Type | Documents |",
        "|---|---:|",
    ]
    for document_type in DOCUMENT_TYPES:
        lines.append(
            f"| {TYPE_LABELS[document_type]} (`{document_type}`) | {counts[document_type]} |"
        )
    lines.extend(["", "## Hard cases", "", "| Case | Left | Right |", "|---|---|---|"])
    for case in payload["hard_cases"]:
        lines.append(
            f"| {case['case_id']} | {case['left_path']} ({case['left_type']}) | "
            f"{case['right_path']} ({case['right_type']}) |"
        )
    lines.extend(
        [
            "",
            "## What this is not",
            "",
            "- Not clause classification.",
            "- Not a new document analysis engine.",
            "- Not a production ingest change.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def refuse_doctype_run_before_gold() -> None:
    raise RuntimeError(
        "document-type gold is not frozen yet. "
        "Do not call Jev before --doctype-gold."
    )


def require_doctype_gold(path: Path | None = None) -> Path:
    target = path or DOCTYPE_GOLD_PATH
    if not target.is_file():
        refuse_doctype_run_before_gold()
    return target
