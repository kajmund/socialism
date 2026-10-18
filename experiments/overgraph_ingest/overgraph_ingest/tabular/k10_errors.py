"""Why k=10 added gold-negative false answers. Saved results only. No new model."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.conclusions import (
    load_tabular_k10_baseline,
    load_tabular_review_baseline,
)
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.tabular.cells import VARIANT_B, VARIANT_K
from overgraph_ingest.tabular.contract import ANSWERED
from overgraph_ingest.tabular.evaluate import FALSE_ANSWER
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[2]
TABULAR_K10_ERRORS_ID = "phase2-tabular-k10-errors-v1"
TABULAR_K10_ERRORS_PATH = ROOT / "baselines" / f"{TABULAR_K10_ERRORS_ID}.json"
GOLD_NARROW = "gold_narrow"
WRONG_RELATION = "wrong_relation"
EXPECTED_NEW_FALSE = 9

# Classify YES does not make a B-cell ANSWERED. Variant B always
# sends every examined unit to answer_cell. The answer call, not
# the classify votes, chooses ANSWERED and the source.
CLASSIFY_GATES_B_ANSWER = False
ANSWER_SEES = "all_examined_units"

# Hand labels after reading the nine frozen excerpts against gold-map v2.
# Ranks are measured from saved candidate keys, not from these notes.
LABELS = {
    ("Avtal_17_Hyresavtal_lokal.docx", "liability-cap"): (
        WRONG_RELATION,
        "Operational driftavbrott disclaimer, not a general cap.",
    ),
    ("Avtal_01_Tillsvidareanstallningsavtal.docx", "auto-renewal"): (
        GOLD_NARROW,
        "Tillsvidareanställning. Gold excludes ongoing tills vidare.",
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
    ("Avtal_10_Arbetstidsavtal_flextid.docx", "notice-period"): (
        GOLD_NARROW,
        "Notice for the flextid addendum, not the employment agreement gold.",
    ),
    ("Avtal_11_Distansarbetsavtal.docx", "confidentiality"): (
        WRONG_RELATION,
        "How to store confidential papers, not a duty to keep information secret.",
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
}


def b_classify_gates_answer() -> bool:
    return CLASSIFY_GATES_B_ANSWER


def run_tabular_k10_errors(
    *,
    review: dict[str, object] | None = None,
    k10: dict[str, object] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    source = review or load_tabular_review_baseline()
    treatment = k10 or load_tabular_k10_baseline()
    b_cells = _index(source.get("cells") or [], VARIANT_B)
    k_cells = _index(treatment.get("cells") or [], VARIANT_K)
    b_scored = _index(source.get("scored") or [], VARIANT_B)
    k_scored = _index(treatment.get("scored") or [], VARIANT_K)
    rows = [_row(key, b_cells[key], k_cells[key], b_scored[key], k_scored[key]) for key in _new_false(b_scored, k_scored)]
    if { (row["relative_path"], row["question_id"]) for row in rows } != set(LABELS):
        raise ValueError("k=10 gold-negative false answers do not match the error table")
    if any(row["cited_in_b_top5"] for row in rows):
        raise ValueError("a new false answer cited a unit already in B k=5")
    return {
        "operation": "tabular_k10_errors",
        "experiment": "tabular_k10_errors_v1",
        "replay_of": ("phase2-tabular-k10-v1", "phase2-tabular-review-v1"),
        "no_new_model": True,
        "no_new_retrieval": True,
        "no_navigation": True,
        "default_k_unchanged": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_k10": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "classify_gates_b_answer": CLASSIFY_GATES_B_ANSWER,
        "answer_sees": ANSWER_SEES,
        "one_yes_is_not_answered": True,
        "rows": rows,
        "headline": {
            "new_gold_negative_false_answers": len(rows),
            "cited_new_tail": sum(1 for row in rows if row["cited_new_tail"]),
            "cited_b_top5": sum(1 for row in rows if row["cited_in_b_top5"]),
            "gold_narrow": sum(1 for row in rows if row["label"] == GOLD_NARROW),
            "wrong_relation": sum(1 for row in rows if row["label"] == WRONG_RELATION),
            "classify_gates_b_answer": CLASSIFY_GATES_B_ANSWER,
            "answer_sees": ANSWER_SEES,
            "same_top5": all(row["top5_unchanged"] for row in rows),
            "verdict": "answer_sees_all_units",
            "next": "do_not_widen_k",
        },
    }


def freeze_tabular_k10_errors(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_K10_ERRORS_ID,
        "label": (
            "Frozen: k=10 gold-negative false answers. Variant B does not "
            "gate ANSWERED on classify YES. The answer call sees every "
            "examined unit. All nine new false answers cited a rank 6-10 "
            "unit. Default k stays 5. Does not replace tabular v1 or k=10."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_k10": True,
        "default_k_unchanged": True,
        "classify_gates_b_answer": CLASSIFY_GATES_B_ANSWER,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline"),
        "rows": payload.get("rows"),
    }


def write_tabular_k10_errors_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_K10_ERRORS_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_k10_errors(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _index(rows: list[object], variant: str) -> dict[tuple[str, str], dict[str, object]]:
    return {
        (str(row["relative_path"]), str(row["question_id"])): row
        for row in rows
        if isinstance(row, dict) and row.get("variant") == variant
    }


def _new_false(
    b_scored: dict[tuple[str, str], dict[str, object]],
    k_scored: dict[tuple[str, str], dict[str, object]],
) -> list[tuple[str, str]]:
    keys = []
    for key, k_row in k_scored.items():
        b_row = b_scored[key]
        if (
            not k_row.get("gold_positive")
            and k_row.get("outcome") == FALSE_ANSWER
            and b_row.get("outcome") != FALSE_ANSWER
        ):
            keys.append(key)
    if len(keys) != EXPECTED_NEW_FALSE:
        raise ValueError(f"expected {EXPECTED_NEW_FALSE} new gold-negative false answers, got {len(keys)}")
    return sorted(keys)


def _row(
    key: tuple[str, str],
    b_cell: dict[str, object],
    k_cell: dict[str, object],
    b_scored: dict[str, object],
    k_scored: dict[str, object],
) -> dict[str, object]:
    b_keys = [str(item) for item in (b_cell.get("retrieval") or {}).get("candidate_keys") or []]
    k_keys = [str(item) for item in (k_cell.get("retrieval") or {}).get("candidate_keys") or []]
    cited = str((k_cell.get("source_unit_ids") or [""])[0])
    rank = k_keys.index(cited) + 1 if cited in k_keys else None
    sources = k_cell.get("sources") or []
    excerpt = ""
    clause = ""
    if sources and isinstance(sources[0], dict):
        excerpt = str(sources[0].get("excerpt") or "")
        clause = str(sources[0].get("clause_number") or "")
    label, note = LABELS[key]
    return {
        "document_id": k_cell.get("document_id"),
        "relative_path": key[0],
        "question_id": key[1],
        "question": USER_QUESTIONS[key[1]],
        "b_status": b_cell.get("status"),
        "k_status": k_cell.get("status"),
        "k_status_is_answered": k_cell.get("status") == ANSWERED,
        "cited_unit_id": cited,
        "cited_rank": rank,
        "cited_in_b_top5": cited in b_keys[:5],
        "cited_new_tail": cited in k_keys[5:],
        "top5_unchanged": b_keys[:5] == k_keys[:5],
        "excerpt": excerpt,
        "clause_number": clause,
        "label": label,
        "note": note,
        "b_outcome": b_scored.get("outcome"),
        "k_outcome": k_scored.get("outcome"),
    }
