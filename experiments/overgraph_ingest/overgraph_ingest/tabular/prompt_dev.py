"""P0-P3 on a frozen development set. The ten known errors are not the selection gold."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.conclusions import load_tabular_signals_baseline
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.cells import answer_without_classify
from overgraph_ingest.tabular.dense_errors import LABELS as DENSE_FALSE
from overgraph_ingest.tabular.evaluate import score_cell, summarize
from overgraph_ingest.tabular.gold import USER_QUESTIONS, cell_relevant_keys, load_tabular_golds
from overgraph_ingest.tabular.prompts import (
    HYPOTHESES,
    INSTRUCTIONS,
    PROMPT_IDS,
    PROMPT_P0,
    instruction_for,
)
from overgraph_ingest.tabular.run import _load_context
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.serialize import cell_payload

ROOT = Path(__file__).resolve().parents[2]
TABULAR_PROMPT_DEV_ID = "phase2-tabular-prompt-dev-v1"
TABULAR_PROMPT_DEV_PATH = ROOT / "baselines" / f"{TABULAR_PROMPT_DEV_ID}.json"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
LISTS = ("hybrid", "dense")
AVTAL_13 = ("Avtal_13_Avgangsvederlagsavtal.docx", "confidentiality")
ERROR_CELLS = tuple(sorted(DENSE_FALSE)) + (AVTAL_13,)
SELECTION_CELLS = (
    ("Avtal_17_Hyresavtal_lokal.docx", "auto-renewal"),
    ("Avtal_18_Hyresavtal_bostad.docx", "notice-period"),
    ("Avtal_05_Konsultavtal.docx", "liability-cap"),
    ("Avtal_06_Sekretessavtal_ensidigt_NDA.docx", "confidentiality"),
    ("Avtal_05_Konsultavtal.docx", "liability-secrecy-carveout"),
    ("Avtal_05_Konsultavtal.docx", "auto-renewal"),
    ("Avtal_06_Sekretessavtal_ensidigt_NDA.docx", "notice-period"),
    ("Avtal_18_Hyresavtal_bostad.docx", "liability-cap"),
    ("Avtal_17_Hyresavtal_lokal.docx", "confidentiality"),
    ("Avtal_17_Hyresavtal_lokal.docx", "liability-secrecy-carveout"),
)
DEV_CELLS = ERROR_CELLS + SELECTION_CELLS


def run_tabular_prompt_dev(
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
    prompts: tuple[str, ...] = PROMPT_IDS,
    lists: tuple[str, ...] = LISTS,
    questions: dict[str, str] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    if set(SELECTION_CELLS) & set(ERROR_CELLS):
        raise ValueError("selection cells must not include the known errors")
    wanted = cells or DEV_CELLS
    asked = questions or USER_QUESTIONS
    gold_by_id = {gold.id: gold for gold in golds or load_tabular_golds(gold_dir or DEFAULT_GOLD_DIR)}
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    by_key = graph.by_key()
    listed = signals or _load_signals(signals_path)
    by_signal = {
        (str(row["relative_path"]), str(row["question_id"])): row
        for row in listed.get("cells") or []
        if isinstance(row, dict)
    }
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for tabular prompt-dev")
    client = jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    started = time.perf_counter()
    results = []
    scored = []
    for relative_path, question_id in wanted:
        gold = gold_by_id[question_id]
        relevant = cell_relevant_keys(graph.units, gold, relative_path)
        signal = by_signal[(relative_path, question_id)]
        for list_name in lists:
            hits = _hits(signal, list_name, by_key, relative_path)
            retrieval = {
                "k": DEFAULT_K,
                "strategy": list_name,
                "candidate_keys": [hit.key for hit in hits],
            }
            for prompt_id in prompts:
                result = answer_without_classify(
                    relative_path=relative_path,
                    question_id=question_id,
                    user_question=asked[question_id],
                    context=graph,
                    seeds=hits,
                    jev=client,
                    jev_model=jev_model,
                    timeout_seconds=jev_timeout_seconds,
                    retrieve_seconds=0.0,
                    retrieval=retrieval,
                    variant=prompt_id,
                    instructions=instruction_for(prompt_id),
                )
                results.append(result)
                row = score_cell(result, relevant)
                row["list"] = list_name
                row["prompt"] = prompt_id
                row["role"] = _role(relative_path, question_id)
                scored.append(row)
                print(
                    f"{prompt_id} {list_name} {result.document_id} {question_id} {result.status}",
                    file=sys.stderr,
                    flush=True,
                )
    wall = time.perf_counter() - started
    by_prompt = {
        prompt_id: [row for row in scored if row["prompt"] == prompt_id] for prompt_id in prompts
    }
    selection = {
        prompt_id: _subset(by_prompt[prompt_id], "selection") for prompt_id in prompts
    }
    errors = {prompt_id: _subset(by_prompt[prompt_id], "error") for prompt_id in prompts}
    picked = pick_prompt(selection)
    usage = {
        prompt_id: _usage(results, prompt_id, scored) for prompt_id in prompts
    }
    selection_by_list = {
        prompt_id: {
            list_name: summarize(
                [row for row in selection[prompt_id] if row.get("list") == list_name]
            )
            if any(row.get("list") == list_name for row in selection[prompt_id])
            else None
            for list_name in lists
        }
        for prompt_id in prompts
    }
    return {
        "operation": "tabular_prompt_dev",
        "experiment": "tabular_prompt_dev_v1",
        "replay_of": "phase2-tabular-signals-v1",
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
        "does_not_replace_c8": True,
        "does_not_replace_tabular_direct": True,
        "selection_is_diagnostic": True,
        "hypotheses": dict(HYPOTHESES),
        "instructions": dict(INSTRUCTIONS),
        "error_cells": [list(item) for item in ERROR_CELLS],
        "selection_cells": [list(item) for item in SELECTION_CELLS],
        "cells": [cell_payload(result) for result in results],
        "scored": scored,
        "by_prompt": {prompt_id: summarize(rows) for prompt_id, rows in by_prompt.items()},
        "selection": {prompt_id: summarize(rows) for prompt_id, rows in selection.items()},
        "errors": {prompt_id: summarize(rows) for prompt_id, rows in errors.items()},
        "picked": picked,
        "changed_from_p0": _changed_from_p0(scored),
        "holdout_not_run": True,
        "usage": usage,
        "selection_by_list": selection_by_list,
        "headline": {
            "picked": picked["prompt"],
            "reason": picked["reason"],
            "selection_true_answers": {
                prompt_id: _count(selection[prompt_id], "true_answer") for prompt_id in prompts
            },
            "selection_false_answers": {
                prompt_id: _count(selection[prompt_id], "false_answer") for prompt_id in prompts
            },
            "selection_cell_accuracy": {
                prompt_id: _cell_accuracy(selection[prompt_id]) for prompt_id in prompts
            },
            "error_false_answers": {
                prompt_id: _count(errors[prompt_id], "false_answer") for prompt_id in prompts
            },
            "uncertain": {
                prompt_id: _status_count(by_prompt[prompt_id], "UNCERTAIN")
                for prompt_id in prompts
            },
            "not_found": {
                prompt_id: _status_count(by_prompt[prompt_id], "NOT_FOUND")
                for prompt_id in prompts
            },
            "usage": usage,
            "changed_from_p0": _changed_from_p0(scored),
            "holdout_not_run": True,
            "known_errors_are_not_selection_gold": True,
            "default_prompt_unchanged": True,
        },
        "wall_seconds": wall,
    }


def pick_prompt(selection: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    if not selection.get(PROMPT_P0):
        return {
            "prompt": PROMPT_P0,
            "reason": "empty_selection",
            "p0_true_answers": 0,
            "eligible": [PROMPT_P0],
            "default_unchanged": True,
        }
    p0_true = _count(selection[PROMPT_P0], "true_answer")
    eligible = [
        prompt_id
        for prompt_id in PROMPT_IDS
        if selection.get(prompt_id) and _count(selection[prompt_id], "true_answer") >= p0_true
    ]
    winner = max(
        eligible,
        key=lambda prompt_id: (
            _cell_accuracy(selection[prompt_id]),
            _count(selection[prompt_id], "true_answer"),
            -_count(selection[prompt_id], "false_answer"),
        ),
    )
    reason = "kept_true_answers_best_cell"
    if winner == PROMPT_P0:
        reason = (
            "p0_remains"
            if eligible == [PROMPT_P0]
            else "p0_tied_or_best_on_selection"
        )
    return {
        "prompt": winner,
        "reason": reason,
        "p0_true_answers": p0_true,
        "eligible": eligible,
        "default_unchanged": True,
    }


def freeze_tabular_prompt_dev(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": TABULAR_PROMPT_DEV_ID,
        "label": (
            "Frozen: P0-P3 answer_cell instructions on a 21-cell development "
            "set, hybrid and dense lists. Known errors are not the selection "
            "gold. Default prompt stays P0. Does not replace D or C@8."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_direct": True,
        "known_errors_are_not_selection_gold": True,
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "no_new_model": True,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline"),
        "picked": payload.get("picked"),
        "changed_from_p0": payload.get("changed_from_p0")
        or _changed_from_p0(payload.get("scored") or []),
        "holdout_not_run": payload.get("holdout_not_run", True),
        "selection": payload.get("selection"),
        "selection_by_list": payload.get("selection_by_list"),
        "errors": payload.get("errors"),
        "by_prompt": payload.get("by_prompt"),
        "usage": payload.get("usage"),
        "hypotheses": payload.get("hypotheses"),
        "error_cells": payload.get("error_cells"),
        "selection_cells": payload.get("selection_cells"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_prompt_dev_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TABULAR_PROMPT_DEV_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_prompt_dev(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _load_signals(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_signals_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _role(relative_path: str, question_id: str) -> str:
    key = (relative_path, question_id)
    if key in ERROR_CELLS:
        return "error"
    if key in SELECTION_CELLS:
        return "selection"
    raise ValueError(f"cell is not in the frozen development set: {key}")


def _subset(rows: list[dict[str, object]], role: str) -> list[dict[str, object]]:
    return [row for row in rows if row.get("role") == role]


def _cell_accuracy(rows: list[dict[str, object]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get("full_success")) / len(rows)


def _changed_from_p0(scored: list[dict[str, object]]) -> list[dict[str, object]]:
    by_key: dict[tuple[str, str, str, str], dict[str, dict[str, object]]] = {}
    for row in scored:
        key = (
            str(row.get("role") or ""),
            str(row.get("list") or ""),
            str(row.get("relative_path") or ""),
            str(row.get("question_id") or ""),
        )
        by_key.setdefault(key, {})[str(row.get("prompt") or "")] = row
    changed = []
    for (role, list_name, relative_path, question_id), rows in sorted(by_key.items()):
        baseline = rows.get(PROMPT_P0)
        if baseline is None:
            continue
        for prompt_id in PROMPT_IDS:
            if prompt_id == PROMPT_P0 or prompt_id not in rows:
                continue
            other = rows[prompt_id]
            if other.get("status") == baseline.get("status") and other.get("outcome") == baseline.get(
                "outcome"
            ):
                continue
            changed.append(
                {
                    "role": role,
                    "list": list_name,
                    "relative_path": relative_path,
                    "question_id": question_id,
                    "prompt": prompt_id,
                    "p0_status": baseline.get("status"),
                    "p0_outcome": baseline.get("outcome"),
                    "status": other.get("status"),
                    "outcome": other.get("outcome"),
                }
            )
    return changed


def _status_count(rows: list[dict[str, object]], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


def _usage(
    results: list[object],
    prompt_id: str,
    scored: list[dict[str, object]],
) -> dict[str, object]:
    matched = [result for result in results if getattr(result, "variant", None) == prompt_id]
    rows = [row for row in scored if row.get("prompt") == prompt_id]
    seconds = [float(row.get("answer_seconds") or 0.0) for row in rows]
    seconds.sort()
    return {
        "jev_calls": sum(int(getattr(result, "jev_calls", 0) or 0) for result in matched),
        "prompt_tokens": sum(int(getattr(result, "prompt_tokens", 0) or 0) for result in matched),
        "completion_tokens": sum(
            int(getattr(result, "completion_tokens", 0) or 0) for result in matched
        ),
        "answer_seconds_sum": round(sum(seconds), 3),
        "answer_seconds_p50": seconds[len(seconds) // 2] if seconds else 0.0,
    }


def _count(rows: list[dict[str, object]], outcome: str) -> int:
    return sum(1 for row in rows if row.get("outcome") == outcome)


def _hits(
    signal: dict[str, object],
    list_name: str,
    by_key: dict[str, StoredUnit],
    relative_path: str,
) -> list[SearchHit]:
    keys = [str(item) for item in (signal.get(list_name) or {}).get("candidate_keys") or []]
    if not keys:
        raise ValueError(f"signals cell is missing {list_name} keys")
    hits = []
    for rank, key in enumerate(keys, start=1):
        unit = by_key.get(key)
        if unit is None:
            raise KeyError(f"{list_name} candidate {key} is missing from the database")
        if unit.relative_path != relative_path:
            raise ValueError(f"{list_name} candidate {key} leaked another document")
        hits.append(
            SearchHit(
                node_id=unit.node_id,
                key=unit.key,
                score=0.0,
                rank=rank,
                document_id=unit.document_id,
                relative_path=unit.relative_path,
                text=unit.text,
            )
        )
    return hits
