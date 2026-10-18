"""Freeze the structure-aware embedding protocol. No Jev. No encode yet."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.tabular.enrich import FIRST_RUN, LOCAL, ORIGINAL, STRUCTURE
from overgraph_ingest.tabular.enrich_dev import (
    DEV_DOCUMENTS,
    DEV_ID,
    DO_NOT_TUNE_CELLS,
    ENRICH_ID,
    RESERVED_DOCUMENTS,
    RESERVED_ID,
    RESERVED_N,
    RESERVED_STRIDE,
    development_cells,
    select_reserved,
    spanned_cells,
)
from overgraph_ingest.tabular.holdout import EXTRA_CORPUS
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_gold import SILENT

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
ENRICH_EVAL_ID = "phase2-tabular-enrich-v1"
ENRICH_EVAL_PATH = ROOT / "baselines" / f"{ENRICH_EVAL_ID}.json"


def review_enrich_protocol() -> dict[str, object]:
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("enrich must leave P0 unchanged")
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    if EXTRA_CORPUS.is_dir() and select_reserved() != RESERVED_DOCUMENTS:
        raise ValueError("reserved holdout drifted from the stride rule")
    cells = development_cells()
    spanned = spanned_cells()
    return {
        "operation": "tabular_enrich_protocol",
        "experiment": ENRICH_EVAL_ID,
        "gold_id": ENRICH_ID,
        "development_id": DEV_ID,
        "reserved_id": RESERVED_ID,
        "does_not_run_jev": True,
        "does_not_run_cerebras": True,
        "does_not_run_qwen": True,
        "does_not_change_ingest": True,
        "does_not_change_default_prompt": True,
        "does_not_change_default_hybrid": True,
        "does_not_change_default_k": True,
        "does_not_write_overgraph": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "search_is_not_evidence": True,
        "no_invented_semantics": True,
        "no_legal_parser": True,
        "hypothesis_2_not_built": True,
        "do_not_tune_known_misses": True,
        "first_run": list(FIRST_RUN),
        "specified_not_run": [LOCAL],
        "representations": {
            ORIGINAL: "original TextUnit text",
            STRUCTURE: "heading ancestry plus original TextUnit",
            LOCAL: "heading ancestry plus previous sibling plus original TextUnit",
        },
        "development_documents": list(DEV_DOCUMENTS),
        "reserved_documents": list(RESERVED_DOCUMENTS),
        "reserved_stride": RESERVED_STRIDE,
        "do_not_tune_cells": [
            {"relative_path": path, "question_id": question_id}
            for path, question_id in DO_NOT_TUNE_CELLS
        ],
        "headline": {
            "development_documents": len(DEV_DOCUMENTS),
            "development_cells": len(cells),
            "spanned_cells": len(spanned),
            "silent_cells": sum(1 for cell in cells if cell.polarity == SILENT),
            "reserved_documents": RESERVED_N,
            "first_run": list(FIRST_RUN),
            "jev_not_run": True,
            "local_context_not_run": True,
        },
    }


def freeze_enrich_protocol(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": ENRICH_EVAL_ID,
        "label": (
            "Structure-aware TextUnit search representations. "
            "A vs B first. Search is not evidence. No Jev. "
            "Reserved holdout is unused."
        ),
        "do_not_overwrite": True,
        "does_not_run_jev": True,
        "does_not_change_ingest": True,
        "search_is_not_evidence": True,
        "hypothesis_2_not_built": True,
        "do_not_tune_known_misses": True,
        "default_remains_d": True,
        "first_run": payload.get("first_run"),
        "specified_not_run": payload.get("specified_not_run"),
        "development_documents": payload.get("development_documents"),
        "reserved_documents": payload.get("reserved_documents"),
        "do_not_tune_cells": payload.get("do_not_tune_cells"),
        "headline": payload.get("headline"),
    }


def write_enrich_protocol_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or ENRICH_EVAL_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_enrich_protocol(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_enrich_protocol_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "enrich-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Structure-aware TextUnit embeddings",
        "",
        "Search representation is not evidence.",
        "Headings come from stored Structure paths.",
        "Previous sibling uses the same structure_id.",
        "No Jev. No legal parser. P0 and default D stay.",
        "",
        "## First run",
        "",
        "| Variant | Search text | Run now |",
        "|---|---|---|",
        "| A | Original TextUnit | Yes |",
        "| B | Heading path + TextUnit | Yes |",
        "| C | Heading path + previous sibling + TextUnit | Later |",
        "",
        f"Development documents: {payload['headline']['development_documents']}.",
        f"Spanned cells: {payload['headline']['spanned_cells']}.",
        f"Reserved holdout: {payload['headline']['reserved_documents']} unused documents.",
        "",
        "Do not tune B to the four known Dense misses.",
        "Hypothesis 2 (Jev at ingest) is not built.",
        "",
        "## Reserved documents",
        "",
    ]
    for path in payload["reserved_documents"]:
        lines.append(f"- {path}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def refuse_enrich_jev() -> None:
    raise RuntimeError(
        "structure-aware embeddings are retrieval-only. Do not call Jev, Cerebras, or Qwen."
    )
