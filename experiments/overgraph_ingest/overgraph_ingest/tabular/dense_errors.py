"""Why dense top-5 added gold-negative false answers. Saved results only."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.conclusions import (
    load_tabular_dense_baseline,
    load_tabular_direct_baseline,
    load_tabular_signals_baseline,
)
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.tabular.cells import VARIANT_D, VARIANT_E
from overgraph_ingest.tabular.contract import ANSWERED, UNCERTAIN
from overgraph_ingest.tabular.evaluate import FALSE_ANSWER
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.k10_errors import LABELS as K10_FALSE
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[2]
TABULAR_DENSE_ERRORS_ID = "phase2-tabular-dense-errors-v1"
TABULAR_DENSE_ERRORS_PATH = ROOT / "baselines" / f"{TABULAR_DENSE_ERRORS_ID}.json"
GOLD_NARROW = "gold_narrow"
WRONG_RELATION = "wrong_relation"
EXPECTED_NEW_FALSE = 10
AVTAL_13 = ("Avtal_13_Avgangsvederlagsavtal.docx", "confidentiality")
AVTAL_13_GOLD = "Arbetstagaren har fortsatt tystnadsplikt om Arbetsgivarens företagshemligheter"

# Hand labels after reading the ten frozen excerpts against gold-map v2.
LABELS = {
    ("Avtal_17_Hyresavtal_lokal.docx", "liability-cap"): (
        WRONG_RELATION,
        "Operational driftavbrott disclaimer, not a general cap.",
    ),
    ("Avtal_36_Underleverantorsavtal.docx", "notice-period"): (
        WRONG_RELATION,
        "Cancellation if the main contract ends, not the general notice.",
    ),
    ("Avtal_04_Timanstallning_behovsanstallning.docx", "auto-renewal"): (
        GOLD_NARROW,
        "Tills vidare with immediate termination. Gold excludes tills vidare.",
    ),
    ("Avtal_04_Timanstallning_behovsanstallning.docx", "confidentiality"): (
        GOLD_NARROW,
        "Operative tystnadsplikt. Gold lists the same duty on Avtal 02/03, not 04.",
    ),
    ("Avtal_08_Konkurrensforbudsavtal.docx", "liability-cap"): (
        WRONG_RELATION,
        "Vite plus excess damages. That is not a liability cap.",
    ),
    ("Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx", "liability-cap"): (
        WRONG_RELATION,
        "Vite plus excess damages. Already in hybrid top-5; D said NOT_FOUND.",
    ),
    ("Avtal_10_Arbetstidsavtal_flextid.docx", "notice-period"): (
        GOLD_NARROW,
        "Notice for the flextid addendum, not the employment agreement gold.",
    ),
    ("Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx", "liability-cap"): (
        WRONG_RELATION,
        "Settlement release, not a standing contractual cap.",
    ),
    (
        "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
        "liability-secrecy-carveout",
    ): (
        WRONG_RELATION,
        "Exception from a settlement release, not from a liability cap.",
    ),
    ("Avtal_13_Avgangsvederlagsavtal.docx", "liability-cap"): (
        WRONG_RELATION,
        "Settlement release after severance pay, not a standing cap.",
    ),
}


def run_tabular_dense_errors(
    *,
    direct: dict[str, object] | None = None,
    dense: dict[str, object] | None = None,
    signals: dict[str, object] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    source = direct or load_tabular_direct_baseline()
    treatment = dense or load_tabular_dense_baseline()
    lists = signals or load_tabular_signals_baseline()
    d_cells = _index(source.get("cells") or [], VARIANT_D)
    e_cells = _index(treatment.get("cells") or [], VARIANT_E)
    d_scored = _index(source.get("scored") or [], VARIANT_D)
    e_scored = _index(treatment.get("scored") or [], VARIANT_E)
    sig = _index(lists.get("cells") or [])
    transitions = _transitions(d_scored, e_scored)
    keys = _new_false(d_scored, e_scored)
    if set(keys) != set(LABELS):
        raise ValueError("dense gold-negative false answers do not match the error table")
    rows = [
        _row(key, d_cells[key], e_cells[key], d_scored[key], e_scored[key], sig[key])
        for key in keys
    ]
    return {
        "operation": "tabular_dense_errors",
        "experiment": "tabular_dense_errors_v1",
        "replay_of": (
            "phase2-tabular-dense-v1",
            "phase2-tabular-direct-v1",
            "phase2-tabular-signals-v1",
        ),
        "performance_reference": VARIANT_D,
        "retrieval_baseline": "hybrid",
        "retrieval_treatment": "dense",
        "no_new_model": True,
        "no_new_retrieval": True,
        "no_navigation": True,
        "no_prompt_change": True,
        "default_k_unchanged": True,
        "default_hybrid_unchanged": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "does_not_replace_tabular_dense": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "selection_is_diagnostic": True,
        "transitions": transitions,
        "rows": rows,
        "avtal_13": _avtal_13(d_cells[AVTAL_13], e_cells[AVTAL_13], sig[AVTAL_13]),
        "headline": {
            "error_to_correct": transitions["error_to_correct"],
            "correct_to_error": transitions["correct_to_error"],
            "uncertain_to_error": transitions["uncertain_to_error"],
            "error_to_other_error": transitions["error_to_other_error"],
            "correct_to_uncertain": transitions["correct_to_uncertain"],
            "same": transitions["same"],
            "new_gold_negative_false_answers": len(rows),
            "cited_new_dense": sum(1 for row in rows if row["cited_new_dense"]),
            "cited_hybrid_already": sum(1 for row in rows if row["cited_in_hybrid"]),
            "gold_narrow": sum(1 for row in rows if row["label"] == GOLD_NARROW),
            "wrong_relation": sum(1 for row in rows if row["label"] == WRONG_RELATION),
            "also_k10_false_positive": sum(1 for row in rows if row["also_k10_false_positive"]),
            "avtal_13_same_cite": True,
            "avtal_13_gold_in_dense_top5": True,
            "verdict": "new_dense_units_drive_false_answers",
            "next": "do_not_change_prompt_until_read",
        },
    }


def freeze_tabular_dense_errors(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_DENSE_ERRORS_ID,
        "label": (
            "Frozen: D vs E error transitions. Ten new gold-negative false "
            "answers. Nine cited a unit that hybrid top-5 did not contain. "
            "Avtal 13 cited settlement secrecy over the gold trade-secret "
            "duty. Hybrid D stays the baseline. No prompt change."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "does_not_replace_tabular_dense": True,
        "no_new_model": True,
        "no_prompt_change": True,
        "default_hybrid_unchanged": True,
        "default_k_unchanged": True,
        "performance_reference": VARIANT_D,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline"),
        "transitions": payload.get("transitions"),
        "rows": payload.get("rows"),
        "avtal_13": payload.get("avtal_13"),
    }


def write_tabular_dense_errors_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_DENSE_ERRORS_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_dense_errors(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _index(rows: list[object], variant: str | None = None) -> dict[tuple[str, str], dict[str, object]]:
    return {
        (str(row["relative_path"]), str(row["question_id"])): row
        for row in rows
        if isinstance(row, dict) and (variant is None or row.get("variant") == variant)
    }


def _new_false(
    d_scored: dict[tuple[str, str], dict[str, object]],
    e_scored: dict[tuple[str, str], dict[str, object]],
) -> list[tuple[str, str]]:
    keys = []
    for key, e_row in e_scored.items():
        d_row = d_scored[key]
        if (
            not e_row.get("gold_positive")
            and e_row.get("outcome") == FALSE_ANSWER
            and d_row.get("outcome") != FALSE_ANSWER
        ):
            keys.append(key)
    if len(keys) != EXPECTED_NEW_FALSE:
        raise ValueError(
            f"expected {EXPECTED_NEW_FALSE} new gold-negative false answers, got {len(keys)}"
        )
    return sorted(keys)


def _transitions(
    d_scored: dict[tuple[str, str], dict[str, object]],
    e_scored: dict[tuple[str, str], dict[str, object]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for key, left in d_scored.items():
        right = e_scored[key]
        d_full = bool(left["full_success"])
        e_full = bool(right["full_success"])
        d_out = str(left["outcome"])
        e_out = str(right["outcome"])
        d_status = str(left["status"])
        if d_out == e_out and left["status"] == right["status"]:
            counts["same"] += 1
        elif (not d_full) and e_full:
            counts["error_to_correct"] += 1
        elif d_full and e_out == FALSE_ANSWER:
            counts["correct_to_error"] += 1
        elif d_full and e_out == "abstention":
            counts["correct_to_uncertain"] += 1
        elif d_status == UNCERTAIN and e_out == FALSE_ANSWER:
            counts["uncertain_to_error"] += 1
        elif (not d_full) and (not e_full) and d_out != e_out:
            counts["error_to_other_error"] += 1
        else:
            counts["other"] += 1
    return {
        "error_to_correct": counts["error_to_correct"],
        "correct_to_error": counts["correct_to_error"],
        "uncertain_to_error": counts["uncertain_to_error"],
        "error_to_other_error": counts["error_to_other_error"],
        "correct_to_uncertain": counts["correct_to_uncertain"],
        "same": counts["same"],
        "other": counts["other"],
        "cells": len(d_scored),
    }


def _row(
    key: tuple[str, str],
    d_cell: dict[str, object],
    e_cell: dict[str, object],
    d_scored: dict[str, object],
    e_scored: dict[str, object],
    signal: dict[str, object],
) -> dict[str, object]:
    hybrid = [str(item) for item in (signal.get("hybrid") or {}).get("candidate_keys") or []]
    dense = [str(item) for item in (signal.get("dense") or {}).get("candidate_keys") or []]
    if not hybrid:
        hybrid = [str(item) for item in (d_cell.get("retrieval") or {}).get("candidate_keys") or []]
    if not dense:
        dense = [str(item) for item in (e_cell.get("retrieval") or {}).get("candidate_keys") or []]
    cited = str((e_cell.get("source_unit_ids") or [""])[0])
    sources = e_cell.get("sources") or []
    excerpt = ""
    clause = ""
    if sources and isinstance(sources[0], dict):
        excerpt = str(sources[0].get("excerpt") or "")
        clause = str(sources[0].get("clause_number") or "")
    label, note = LABELS[key]
    return {
        "document_id": e_cell.get("document_id"),
        "relative_path": key[0],
        "question_id": key[1],
        "question": USER_QUESTIONS[key[1]],
        "d_status": d_cell.get("status"),
        "e_status": e_cell.get("status"),
        "e_status_is_answered": e_cell.get("status") == ANSWERED,
        "added_keys": [item for item in dense if item not in hybrid],
        "removed_keys": [item for item in hybrid if item not in dense],
        "cited_unit_id": cited,
        "cited_rank": dense.index(cited) + 1 if cited in dense else None,
        "cited_in_hybrid": cited in hybrid,
        "cited_new_dense": cited in dense and cited not in hybrid,
        "excerpt": excerpt,
        "clause_number": clause,
        "label": label,
        "note": note,
        "also_k10_false_positive": key in K10_FALSE,
        "d_outcome": d_scored.get("outcome"),
        "e_outcome": e_scored.get("outcome"),
    }


def _avtal_13(
    d_cell: dict[str, object],
    e_cell: dict[str, object],
    signal: dict[str, object],
) -> dict[str, object]:
    cited = str((e_cell.get("source_unit_ids") or [""])[0])
    gold_keys = [str(item) for item in signal.get("relevant_keys") or []]
    sources = e_cell.get("sources") or []
    excerpt = ""
    if sources and isinstance(sources[0], dict):
        excerpt = str(sources[0].get("excerpt") or "")
    return {
        "relative_path": AVTAL_13[0],
        "question_id": AVTAL_13[1],
        "question": USER_QUESTIONS[AVTAL_13[1]],
        "d_cited": str((d_cell.get("source_unit_ids") or [""])[0]),
        "e_cited": cited,
        "same_cite": cited == str((d_cell.get("source_unit_ids") or [""])[0]),
        "gold_keys": gold_keys,
        "cited_is_gold": cited in gold_keys,
        "dense_gold_rank": (signal.get("dense") or {}).get("gold_rank"),
        "hybrid_gold_rank": (signal.get("hybrid") or {}).get("gold_rank"),
        "cited_excerpt": excerpt,
        "gold_contains": AVTAL_13_GOLD,
        "label": WRONG_RELATION,
        "note": (
            "Cited confidentiality of this settlement. Gold is the ongoing "
            "trade-secret duty. Same cite as hybrid D; gold was dense rank 3."
        ),
    }
