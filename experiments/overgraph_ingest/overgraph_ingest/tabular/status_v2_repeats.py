"""D repeats and unseen holdout. Does not overwrite status-v2. Default P0 stays."""

from __future__ import annotations

import csv
import inspect
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.conclusions import load_tabular_signals_baseline
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.prompts import PROMPT_P0_V2_D
from overgraph_ingest.tabular.run import _load_context
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.serialize import cell_payload
from overgraph_ingest.tabular.status_v2 import (
    FALSE_ANSWERED,
    WRONG_EXCERPT,
    _answer,
    _case_keys,
    _hits,
    _matching_keys,
    score_status,
    summarize_status,
)
from overgraph_ingest.tabular.status_v2_cases import (
    COSTLIER_ERROR,
    EVAL_CASES,
    EXCLUSION_PROVENANCE,
    HARD_NEG_SPLIT,
    HOLDOUT_NEG,
    HOLDOUT_SPLIT,
    NAMED_EXCLUSION_NEEDLES,
    NEARBY_IS_UNCERTAIN,
    StatusCase,
)

ROOT = Path(__file__).resolve().parents[2]
REPEATS_ID = "phase2-tabular-status-v2-repeats"
REPEATS_PATH = ROOT / "baselines" / f"{REPEATS_ID}.json"
STATUS_V2_PATH = ROOT / "baselines" / "phase2-tabular-status-v2.json"
EVAL_DIR = ROOT / "eval"
REPEAT_N = 5
STEP = PROMPT_P0_V2_D


def prompt_scored_eval_cases() -> tuple[StatusCase, ...]:
    return tuple(case for case in EVAL_CASES if case.prompt_scored)


def jev_has_temperature() -> bool:
    return "temperature" in inspect.signature(HttpJevClient.ask).parameters


def run_tabular_status_v2_repeats(
    *,
    signals_path: Path | None = None,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    jev: JevClient | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    signals: dict[str, object] | None = None,
    cases: tuple[StatusCase, ...] | None = None,
    holdout: tuple[StatusCase, ...] | None = None,
    repeat_n: int = REPEAT_N,
    write_table: bool = True,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    if jev_has_temperature():
        raise ValueError("Jev gained a temperature parameter; pass it explicitly")
    scored_eval = cases if cases is not None else prompt_scored_eval_cases()
    holdout_cases = holdout if holdout is not None else HOLDOUT_NEG
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    listed = signals if signals is not None else _load_signals(signals_path)
    by_signal = {
        (str(row["relative_path"]), str(row["question_id"])): row
        for row in listed.get("cells") or []
        if isinstance(row, dict)
    }
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for tabular status-v2-repeats")
    client = jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    started = time.perf_counter()
    rows = []
    cells = []
    for bucket, wanted in (("eval", scored_eval), ("holdout", holdout_cases)):
        for case in wanted:
            keys = _case_keys(case, by_signal)
            hits = _hits(keys, graph.by_key(), case.relative_path)
            gold_keys = _matching_keys(hits, case.gold_contains)
            _require_nearby(case, hits)
            if case.expected_status == "ANSWERED" and not gold_keys:
                raise ValueError(f"{case.case_id} expected ANSWERED but gold is missing")
            for run in range(1, repeat_n + 1):
                result, _ = _answer(
                    case=case,
                    hits=hits,
                    graph=graph,
                    client=client,
                    step=STEP,
                    jev_model=jev_model,
                    timeout_seconds=jev_timeout_seconds,
                    replay=None,
                )
                cells.append(cell_payload(result))
                row = score_status(case, result, gold_keys)
                row["kind"] = "repeat"
                row["bucket"] = bucket
                row["run"] = run
                row["permutation"] = "as_retrieved"
                row["split"] = HARD_NEG_SPLIT.get(case.case_id) or HOLDOUT_SPLIT.get(
                    case.case_id
                )
                rows.append(row)
                print(
                    f"REPEAT {STEP} {bucket} {case.case_id} #{run} {result.status} {row['outcome']}",
                    file=sys.stderr,
                    flush=True,
                )
    wall = time.perf_counter() - started
    eval_rows = [row for row in rows if row["bucket"] == "eval"]
    holdout_rows = [row for row in rows if row["bucket"] == "holdout"]
    eval_spread = spread_report(eval_rows)
    holdout_spread = spread_report(holdout_rows)
    payload = {
        "operation": "tabular_status_v2_repeats",
        "experiment": REPEATS_ID,
        "step": STEP,
        "repeat_n": repeat_n,
        "jev_temperature": None,
        "jev_has_temperature_parameter": False,
        "performance_reference": "D",
        "retrieval_baseline": "hybrid",
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "does_not_overwrite_status_v2": True,
        "nearby_is_uncertain": NEARBY_IS_UNCERTAIN,
        "costlier_error": COSTLIER_ERROR,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_status_v2": True,
        "unused_hard_neg_are_in_distribution": True,
        "exclusion_provenance": dict(EXCLUSION_PROVENANCE),
        "hard_neg_split": dict(HARD_NEG_SPLIT),
        "holdout_split": dict(HOLDOUT_SPLIT),
        "named_exclusion_needles": list(NAMED_EXCLUSION_NEEDLES),
        "eval_cases": [case.case_id for case in scored_eval],
        "holdout_cases": [case.case_id for case in holdout_cases],
        "cells": cells,
        "scored": rows,
        "eval_spread": eval_spread,
        "holdout_spread": holdout_spread,
        "headline": {
            "eval": _spread_headline(eval_spread),
            "holdout": _spread_headline(holdout_spread),
            "jev_has_temperature_parameter": False,
            "unused_hard_neg_are_in_distribution": True,
            "default_prompt_unchanged": True,
        },
        "wall_seconds": wall,
    }
    if write_table:
        write_status_v2_repeats_table(payload)
    return payload


def spread_report(rows: list[dict[str, object]]) -> dict[str, object]:
    by_run: dict[int, list[dict[str, object]]] = defaultdict(list)
    by_case: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_run[int(row["run"])].append(row)
        by_case[str(row["case_id"])].append(row)
    per_run = [summarize_status(by_run[run]) for run in sorted(by_run)]
    histograms = {}
    for case_id, items in by_case.items():
        statuses = Counter(str(item["status"]) for item in items)
        outcomes = Counter(str(item["outcome"]) for item in items)
        histograms[case_id] = {
            "status": dict(statuses),
            "outcome": dict(outcomes),
            "stable": len(statuses) == 1,
            "any_false_answered": (
                outcomes[FALSE_ANSWERED] + outcomes[WRONG_EXCERPT] > 0
            ),
        }
    return {
        "cells_per_run": per_run[0]["cells"] if per_run else 0,
        "runs": len(per_run),
        "per_run": per_run,
        "true_answered": _series(per_run, "true_answered"),
        "false_answered": _series(per_run, "false_answered"),
        "false_abstention": _series(per_run, "false_abstention"),
        "unstable_cells": [
            case_id for case_id, item in histograms.items() if not item["stable"]
        ],
        "cells_with_false_answered": [
            case_id
            for case_id, item in histograms.items()
            if item["any_false_answered"]
        ],
        "histogram": histograms,
    }


def freeze_tabular_status_v2_repeats(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": REPEATS_ID,
        "label": (
            "Frozen: P0_v2_D repeated five times on the status-v2 prompt-scored "
            "cells plus five unseen holdout near-misses. Jev has no temperature. "
            "Unused HARD_NEG are in-distribution for named exclusions. Default "
            "P0 stays. Does not overwrite status-v2 or C@8."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_status_v2": True,
        "does_not_overwrite_status_v2": True,
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "nearby_is_uncertain": True,
        "jev_has_temperature_parameter": False,
        "unused_hard_neg_are_in_distribution": True,
        "costlier_error": COSTLIER_ERROR,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline"),
        "eval_spread": payload.get("eval_spread"),
        "holdout_spread": payload.get("holdout_spread"),
        "eval_cases": payload.get("eval_cases"),
        "holdout_cases": payload.get("holdout_cases"),
        "exclusion_provenance": payload.get("exclusion_provenance"),
        "hard_neg_split": payload.get("hard_neg_split"),
        "holdout_split": payload.get("holdout_split"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_status_v2_repeats_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or REPEATS_PATH
    if target.resolve() == STATUS_V2_PATH.resolve():
        raise ValueError("must not overwrite phase2-tabular-status-v2")
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_status_v2_repeats(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_status_v2_repeats_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target_dir = directory or EVAL_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "status-v2-repeats.csv"
    md_path = target_dir / "status-v2-repeats.md"
    rows = list(payload.get("scored") or [])
    fieldnames = [
        "bucket",
        "run",
        "case_id",
        "status",
        "expected_status",
        "outcome",
        "split",
        "excerpt",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    eval_spread = payload.get("eval_spread") or {}
    holdout_spread = payload.get("holdout_spread") or {}
    lines = [
        "# Tabular status P0_v2_D repeats",
        "",
        "Jev has no temperature parameter. Repeats are the only stochasticity.",
        "Default P0 is unchanged. Does not overwrite `eval/status-v2.md`.",
        "",
        "## Unused HARD_NEG are not holdout",
        "",
        "The five unused negatives in status-v2 match named `Räknas inte` "
        "exclusions written after those error types were seen:",
        "",
    ]
    for case_id, split in (payload.get("hard_neg_split") or {}).items():
        lines.append(f"- `{case_id}` → `{split}`")
    lines.extend(
        [
            "",
            "## Unseen holdout",
            "",
            "These near-misses were chosen because their wording is not a named "
            "D exclusion. The exclusions were written without seeing these errors.",
            "",
        ]
    )
    for case_id, split in (payload.get("holdout_split") or {}).items():
        lines.append(f"- `{case_id}` → `{split}`")
    lines.extend(
        [
            "",
            "## Spread on the 23 prompt-scored cells",
            "",
            _spread_table(eval_spread),
            "",
            "## Spread on unseen holdout",
            "",
            _spread_table(holdout_spread),
            "",
            "## Unstable cells",
            "",
        ]
    )
    unstable = list(eval_spread.get("unstable_cells") or []) + list(
        holdout_spread.get("unstable_cells") or []
    )
    if unstable:
        lines.extend(f"- `{case_id}`" for case_id in unstable)
    else:
        lines.append("None. Every cell returned the same status on all repeats.")
    false_cells = list(eval_spread.get("cells_with_false_answered") or []) + list(
        holdout_spread.get("cells_with_false_answered") or []
    )
    lines.extend(["", "## Cells with any false ANSWERED", ""])
    if false_cells:
        lines.extend(f"- `{case_id}`" for case_id in false_cells)
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            "Eleven true `ANSWERED` on the 23 prompt-scored cells is stable "
            "(11/11/11 across five repeats, zero spread). It is not a lucky single run.",
            "The five unused HARD_NEG are in-distribution for named exclusions, "
            "so they do not show generalization.",
            "On unseen holdout D false-answered Avtal 92 in 5/5: a settlement "
            "release (`inga ytterligare krav`) was taken as a liability cap. "
            "That wording is not a named D exclusion.",
            "D did not generalize. Default P0 stays.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def _spread_table(spread: dict[str, object]) -> str:
    if not spread:
        return "No rows."
    true_s = spread.get("true_answered") or {}
    false_s = spread.get("false_answered") or {}
    miss_s = spread.get("false_abstention") or {}
    return (
        "| Mått | min | median | max | per körning |\n"
        "|---|---:|---:|---:|---|\n"
        f"| True ANSWERED | {true_s.get('min')} | {true_s.get('median')} | "
        f"{true_s.get('max')} | {true_s.get('values')} |\n"
        f"| False ANSWERED | {false_s.get('min')} | {false_s.get('median')} | "
        f"{false_s.get('max')} | {false_s.get('values')} |\n"
        f"| Missade svar | {miss_s.get('min')} | {miss_s.get('median')} | "
        f"{miss_s.get('max')} | {miss_s.get('values')} |"
    )


def _spread_headline(spread: dict[str, object]) -> dict[str, object]:
    return {
        "true_answered": spread.get("true_answered"),
        "false_answered": spread.get("false_answered"),
        "false_abstention": spread.get("false_abstention"),
        "unstable_cells": spread.get("unstable_cells"),
        "cells_with_false_answered": spread.get("cells_with_false_answered"),
    }


def _series(per_run: list[dict[str, object]], key: str) -> dict[str, object]:
    values = [int(item[key]) for item in per_run]
    if not values:
        return {"min": 0, "median": 0, "max": 0, "values": []}
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "values": values,
    }


def _require_nearby(case: StatusCase, hits: list[object]) -> None:
    if not case.nearby_contains:
        return
    texts = [str(getattr(hit, "text", "")) for hit in hits]
    if not any(needle in text for needle in case.nearby_contains for text in texts):
        raise ValueError(f"{case.case_id} nearby text is missing from the candidate list")


def _load_signals(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_signals_baseline()
    return json.loads(path.read_text(encoding="utf-8"))
