"""Same P0 instruction with English questions. Frozen Swedish P0 stays the reference."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.client import JevClient
from overgraph_ingest.retrieval.conclusions import load_tabular_prompt_dev_baseline
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.evaluate import summarize
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.prompt_dev import (
    DEV_CELLS,
    ERROR_CELLS,
    SELECTION_CELLS,
    _cell_accuracy,
    _count,
    _status_count,
    _usage,
    run_tabular_prompt_dev,
)
from overgraph_ingest.tabular.prompts import ENGLISH_QUESTIONS, PROMPT_P0, PROMPT_P0_EN
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[2]
TABULAR_PROMPT_EN_ID = "phase2-tabular-prompt-en-v1"
TABULAR_PROMPT_EN_PATH = ROOT / "baselines" / f"{TABULAR_PROMPT_EN_ID}.json"
PROMPT_SV = "P0_SV"


def run_tabular_prompt_en(
    *,
    signals_path: Path | None = None,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    jev: JevClient | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    golds: list[RetrievalGold] | None = None,
    signals: dict[str, object] | None = None,
    cells: tuple[tuple[str, str], ...] | None = None,
    reference: dict[str, object] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    if set(USER_QUESTIONS) != set(ENGLISH_QUESTIONS):
        raise ValueError("English questions must cover the same ids")
    live = run_tabular_prompt_dev(
        signals_path=signals_path,
        db_path=db_path,
        gold_dir=gold_dir,
        dense_dimension=dense_dimension,
        typesafe_api_key=typesafe_api_key,
        typesafe_base_url=typesafe_base_url,
        jev_model=jev_model,
        jev_timeout_seconds=jev_timeout_seconds,
        jev=jev,
        units=units,
        structures=structures,
        golds=golds,
        signals=signals,
        cells=cells,
        prompts=(PROMPT_P0,),
        questions=ENGLISH_QUESTIONS,
    )
    english = _relabel(live, PROMPT_P0_EN)
    swedish = _swedish_p0(reference or load_tabular_prompt_dev_baseline(), cells or DEV_CELLS)
    scored = swedish["scored"] + english["scored"]
    selection = {
        PROMPT_SV: swedish["selection"],
        PROMPT_P0_EN: english["selection"],
    }
    errors = {
        PROMPT_SV: swedish["errors"],
        PROMPT_P0_EN: english["errors"],
    }
    picked = pick_language(selection)
    changed = _paired_changes(swedish["scored"], english["scored"])
    return {
        "operation": "tabular_prompt_en",
        "experiment": "tabular_prompt_en_v1",
        "replay_of": "phase2-tabular-prompt-dev-v1",
        "performance_reference": "D",
        "retrieval_baseline": "hybrid",
        "known_errors_are_not_selection_gold": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "no_new_model": True,
        "no_navigation": True,
        "default_k_unchanged": True,
        "default_hybrid_unchanged": True,
        "default_prompt_unchanged": True,
        "default_question_language_unchanged": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_prompt_dev": True,
        "prior_instructions_were_already_english": True,
        "hypothesis": "Same P0 instruction; only the question language changes.",
        "swedish_questions": dict(USER_QUESTIONS),
        "english_questions": dict(ENGLISH_QUESTIONS),
        "error_cells": [list(item) for item in ERROR_CELLS],
        "selection_cells": [list(item) for item in SELECTION_CELLS],
        "cells": english["cells"],
        "scored": scored,
        "selection": {
            PROMPT_SV: swedish["selection_summary"],
            PROMPT_P0_EN: english["selection_summary"],
        },
        "errors": {
            PROMPT_SV: swedish["errors_summary"],
            PROMPT_P0_EN: english["errors_summary"],
        },
        "by_prompt": {
            PROMPT_SV: swedish["by_prompt"],
            PROMPT_P0_EN: english["by_prompt"],
        },
        "picked": picked,
        "changed_from_swedish": changed,
        "holdout_not_run": True,
        "usage": {
            PROMPT_SV: swedish["usage"],
            PROMPT_P0_EN: english["usage"],
        },
        "headline": {
            "picked": picked["prompt"],
            "reason": picked["reason"],
            "selection_true_answers": {
                PROMPT_SV: _count(selection[PROMPT_SV], "true_answer"),
                PROMPT_P0_EN: _count(selection[PROMPT_P0_EN], "true_answer"),
            },
            "selection_false_answers": {
                PROMPT_SV: _count(selection[PROMPT_SV], "false_answer"),
                PROMPT_P0_EN: _count(selection[PROMPT_P0_EN], "false_answer"),
            },
            "selection_cell_accuracy": {
                PROMPT_SV: _cell_accuracy(selection[PROMPT_SV]),
                PROMPT_P0_EN: _cell_accuracy(selection[PROMPT_P0_EN]),
            },
            "error_false_answers": {
                PROMPT_SV: _count(errors[PROMPT_SV], "false_answer"),
                PROMPT_P0_EN: _count(errors[PROMPT_P0_EN], "false_answer"),
            },
            "uncertain": {
                PROMPT_SV: _status_count(swedish["scored"], "UNCERTAIN"),
                PROMPT_P0_EN: _status_count(english["scored"], "UNCERTAIN"),
            },
            "not_found": {
                PROMPT_SV: _status_count(swedish["scored"], "NOT_FOUND"),
                PROMPT_P0_EN: _status_count(english["scored"], "NOT_FOUND"),
            },
            "changed_from_swedish": changed,
            "prior_instructions_were_already_english": True,
            "holdout_not_run": True,
            "default_prompt_unchanged": True,
            "default_question_language_unchanged": True,
        },
        "wall_seconds": live["wall_seconds"],
    }


def pick_language(selection: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    sv_true = _count(selection[PROMPT_SV], "true_answer")
    en_true = _count(selection[PROMPT_P0_EN], "true_answer")
    if en_true < sv_true:
        return {
            "prompt": PROMPT_SV,
            "reason": "english_lost_true_answers",
            "swedish_true_answers": sv_true,
            "english_true_answers": en_true,
            "default_unchanged": True,
        }
    if _cell_accuracy(selection[PROMPT_P0_EN]) > _cell_accuracy(selection[PROMPT_SV]):
        return {
            "prompt": PROMPT_P0_EN,
            "reason": "english_kept_true_better_cell",
            "swedish_true_answers": sv_true,
            "english_true_answers": en_true,
            "default_unchanged": True,
        }
    return {
        "prompt": PROMPT_SV,
        "reason": "swedish_tied_or_best",
        "swedish_true_answers": sv_true,
        "english_true_answers": en_true,
        "default_unchanged": True,
    }


def freeze_tabular_prompt_en(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_PROMPT_EN_ID,
        "label": (
            "Frozen: same P0 instruction with English questions on the "
            "21-cell development set. Prior P1-P3 instructions were already "
            "English. Default question language stays Swedish. Does not "
            "replace P0 or C@8."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_prompt_dev": True,
        "known_errors_are_not_selection_gold": True,
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "default_question_language_unchanged": True,
        "prior_instructions_were_already_english": True,
        "no_new_model": True,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline"),
        "picked": payload.get("picked"),
        "selection": payload.get("selection"),
        "errors": payload.get("errors"),
        "by_prompt": payload.get("by_prompt"),
        "changed_from_swedish": payload.get("changed_from_swedish"),
        "holdout_not_run": payload.get("holdout_not_run", True),
        "swedish_questions": payload.get("swedish_questions"),
        "english_questions": payload.get("english_questions"),
        "error_cells": payload.get("error_cells"),
        "selection_cells": payload.get("selection_cells"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "usage": payload.get("usage"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_prompt_en_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_PROMPT_EN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_prompt_en(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _relabel(payload: dict[str, object], prompt_id: str) -> dict[str, object]:
    scored = []
    for row in payload.get("scored") or []:
        item = dict(row)
        item["prompt"] = prompt_id
        scored.append(item)
    cells = []
    for row in payload.get("cells") or []:
        item = dict(row)
        item["variant"] = prompt_id
        cells.append(item)
    selection = [row for row in scored if row.get("role") == "selection"]
    errors = [row for row in scored if row.get("role") == "error"]
    usage = payload.get("usage") or {}
    return {
        "cells": cells,
        "scored": scored,
        "selection": selection,
        "errors": errors,
        "selection_summary": (payload.get("selection") or {}).get(PROMPT_P0),
        "errors_summary": (payload.get("errors") or {}).get(PROMPT_P0),
        "by_prompt": (payload.get("by_prompt") or {}).get(PROMPT_P0),
        "usage": usage.get(PROMPT_P0) or _usage([], prompt_id, scored),
    }


def _swedish_p0(
    reference: dict[str, object],
    cells: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    wanted = set(cells)
    scored = []
    for row in reference.get("scored") or []:
        if row.get("prompt") != PROMPT_P0:
            continue
        key = (str(row.get("relative_path")), str(row.get("question_id")))
        if key not in wanted:
            continue
        item = dict(row)
        item["prompt"] = PROMPT_SV
        scored.append(item)
    if not scored:
        raise ValueError("frozen Swedish P0 rows are missing")
    selection = [row for row in scored if row.get("role") == "selection"]
    errors = [row for row in scored if row.get("role") == "error"]
    summaries = reference.get("selection") or {}
    error_summaries = reference.get("errors") or {}
    by_prompt = reference.get("by_prompt") or {}
    usage = (reference.get("usage") or {}).get(PROMPT_P0) or _usage([], PROMPT_SV, scored)
    return {
        "cells": [],
        "scored": scored,
        "selection": selection,
        "errors": errors,
        "selection_summary": summaries.get(PROMPT_P0)
        if set(cells) == set(DEV_CELLS)
        else summarize(selection)
        if selection
        else None,
        "errors_summary": error_summaries.get(PROMPT_P0)
        if set(cells) == set(DEV_CELLS)
        else summarize(errors)
        if errors
        else None,
        "by_prompt": by_prompt.get(PROMPT_P0)
        if set(cells) == set(DEV_CELLS)
        else summarize(scored),
        "usage": usage,
    }


def _paired_changes(
    swedish: list[dict[str, object]],
    english: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_en = {
        (
            str(row.get("role") or ""),
            str(row.get("list") or ""),
            str(row.get("relative_path") or ""),
            str(row.get("question_id") or ""),
        ): row
        for row in english
    }
    changed = []
    for row in swedish:
        key = (
            str(row.get("role") or ""),
            str(row.get("list") or ""),
            str(row.get("relative_path") or ""),
            str(row.get("question_id") or ""),
        )
        other = by_en.get(key)
        if other is None:
            continue
        if other.get("status") == row.get("status") and other.get("outcome") == row.get("outcome"):
            continue
        changed.append(
            {
                "role": key[0],
                "list": key[1],
                "relative_path": key[2],
                "question_id": key[3],
                "swedish_status": row.get("status"),
                "swedish_outcome": row.get("outcome"),
                "english_status": other.get("status"),
                "english_outcome": other.get("outcome"),
            }
        )
    return changed
