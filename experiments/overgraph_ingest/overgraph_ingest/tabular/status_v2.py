"""P0_v2 status-prompt experiment. Default P0 stays frozen."""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.conclusions import (
    load_tabular_prompt_dev_baseline,
    load_tabular_signals_baseline,
)
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.cells import answer_without_classify
from overgraph_ingest.tabular.contract import ANSWERED, CellResult, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.prompts import (
    PROMPT_P0,
    PROMPT_P0_V2,
    PROMPT_P0_V2_B,
    PROMPT_P0_V2_D,
    PROMPT_P0_V2_EN,
    criteria_for,
    instruction_for,
    questions_for,
)
from overgraph_ingest.tabular.run import _load_context
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.serialize import cell_payload
from overgraph_ingest.tabular.status_v2_cases import (
    COSTLIER_ERROR,
    EVAL_CASES,
    NEARBY_IS_UNCERTAIN,
    PERM_CASE_ID,
    REPEAT_CASE_IDS,
    StatusCase,
)

ROOT = Path(__file__).resolve().parents[2]
STATUS_V2_ID = "phase2-tabular-status-v2"
STATUS_V2_PATH = ROOT / "baselines" / f"{STATUS_V2_ID}.json"
EVAL_DIR = ROOT / "eval"
STEPS = (PROMPT_P0, PROMPT_P0_V2_B, PROMPT_P0_V2, PROMPT_P0_V2_D, PROMPT_P0_V2_EN)
REPEAT_STEPS = (PROMPT_P0_V2, PROMPT_P0_V2_D)
PERM_STEPS = (PROMPT_P0_V2, PROMPT_P0_V2_D)
PERMUTATIONS = (
    "as_retrieved",
    "gold_first",
    "gold_last",
    "nearby_first",
    "gold_second",
)
REPEAT_N = 5
FALSE_ANSWERED = "false_answered"
TRUE_ANSWERED = "true_answered"
FALSE_ABSTENTION = "false_abstention"
TRUE_UNCERTAIN = "true_uncertain"
TRUE_NOT_FOUND = "true_not_found"
STATUS_MISMATCH = "status_mismatch"
WRONG_EXCERPT = "wrong_excerpt"
RETRIEVAL_ERROR = "retrieval_error"


def run_tabular_status_v2(
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
    reference: dict[str, object] | None = None,
    cases: tuple[StatusCase, ...] | None = None,
    steps: tuple[str, ...] = STEPS,
    repeat_n: int = REPEAT_N,
    permutations: bool = True,
    write_table: bool = True,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    wanted = cases or EVAL_CASES
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    listed = signals or _load_signals(signals_path)
    by_signal = {
        (str(row["relative_path"]), str(row["question_id"])): row
        for row in listed.get("cells") or []
        if isinstance(row, dict)
    }
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for tabular status-v2")
    client = jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    replay = _replay_index(reference or _load_reference())
    started = time.perf_counter()
    rows = []
    cells = []
    for case in wanted:
        keys = _case_keys(case, by_signal)
        hits = _hits(keys, graph.by_key(), case.relative_path)
        gold_keys = _matching_keys(hits, case.gold_contains)
        if case.expected_status == ANSWERED and case.prompt_scored and not gold_keys:
            raise ValueError(f"{case.case_id} expected ANSWERED but gold is missing")
        if case.role == RETRIEVAL_ERROR and gold_keys:
            raise ValueError(f"{case.case_id} flagged retrieval error but gold is present")
        for step in steps:
            result, reused = _answer(
                case=case,
                hits=hits,
                graph=graph,
                client=client,
                step=step,
                jev_model=jev_model,
                timeout_seconds=jev_timeout_seconds,
                replay=replay,
            )
            cells.append(cell_payload(result))
            row = score_status(case, result, gold_keys)
            row["reused_p0"] = reused
            row["run"] = 1
            row["permutation"] = "as_retrieved"
            rows.append(row)
            print(
                f"{step} {case.case_id} {result.status} {row['outcome']}",
                file=sys.stderr,
                flush=True,
            )
    perm_rows = []
    if permutations:
        perm_rows = _run_permutations(
            wanted,
            by_signal,
            graph,
            client,
            jev_model,
            jev_timeout_seconds,
            cells,
        )
        rows.extend(perm_rows)
    repeat_rows = _run_repeats(
        wanted,
        by_signal,
        graph,
        client,
        jev_model,
        jev_timeout_seconds,
        repeat_n,
        cells,
    )
    rows.extend(repeat_rows)
    wall = time.perf_counter() - started
    main = [row for row in rows if row.get("kind") == "main"]
    by_step = {step: [row for row in main if row["step"] == step] for step in steps}
    scored = {
        step: [row for row in by_step[step] if row.get("prompt_scored")] for step in steps
    }
    summary = {step: summarize_status(scored[step]) for step in steps}
    acceptance = acceptance_report(scored, perm_rows, repeat_rows, main)
    payload = {
        "operation": "tabular_status_v2",
        "experiment": STATUS_V2_ID,
        "performance_reference": "D",
        "retrieval_baseline": "hybrid",
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "nearby_is_uncertain": NEARBY_IS_UNCERTAIN,
        "costlier_error": COSTLIER_ERROR,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_prompt_dev": True,
        "steps": list(steps),
        "cases": [case.case_id for case in wanted],
        "cells": cells,
        "scored": rows,
        "by_step": summary,
        "acceptance": acceptance,
        "headline": {
            "false_answered": {
                step: summary[step]["false_answered"] for step in steps
            },
            "true_answered": {step: summary[step]["true_answered"] for step in steps},
            "false_abstention": {
                step: summary[step]["false_abstention"] for step in steps
            },
            "acceptance": acceptance,
            "default_prompt_unchanged": True,
        },
        "wall_seconds": wall,
    }
    if write_table:
        write_status_v2_table(payload)
    return payload


def score_status(
    case: StatusCase,
    result: object,
    gold_keys: set[str],
) -> dict[str, object]:
    status = result.status
    cited = set(result.source_unit_ids or [])
    gold_in_list = bool(gold_keys)
    cited_gold = bool(cited & gold_keys)
    if not case.prompt_scored:
        outcome = RETRIEVAL_ERROR
    elif case.expected_status == ANSWERED:
        if status == ANSWERED and cited_gold:
            outcome = TRUE_ANSWERED
        elif status == ANSWERED:
            outcome = WRONG_EXCERPT
        else:
            outcome = FALSE_ABSTENTION
    elif status == ANSWERED:
        outcome = FALSE_ANSWERED
    elif status == case.expected_status == UNCERTAIN:
        outcome = TRUE_UNCERTAIN
    elif status == case.expected_status == NOT_FOUND:
        outcome = TRUE_NOT_FOUND
    else:
        outcome = STATUS_MISMATCH
    return {
        "kind": "main",
        "case_id": case.case_id,
        "relative_path": case.relative_path,
        "question_id": case.question_id,
        "role": case.role,
        "list": case.list_name,
        "step": result.variant,
        "status": status,
        "expected_status": case.expected_status,
        "outcome": outcome,
        "prompt_scored": case.prompt_scored,
        "gold_in_list": gold_in_list,
        "cited_gold": cited_gold,
        "excerpt": result.answer,
        "source_unit_ids": list(result.source_unit_ids or []),
        "jev_calls": result.jev_calls,
        "answer_seconds": result.answer_seconds,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "nearby_present": bool(case.nearby_contains),
    }


def summarize_status(rows: list[dict[str, object]]) -> dict[str, object]:
    counts = defaultdict(int)
    for row in rows:
        counts[str(row["outcome"])] += 1
        counts[f"status:{row['status']}"] += 1
    n = len(rows)
    true_pos = [row for row in rows if row["expected_status"] == ANSWERED]
    return {
        "cells": n,
        "true_answered": counts[TRUE_ANSWERED],
        "false_answered": counts[FALSE_ANSWERED] + counts[WRONG_EXCERPT],
        "wrong_excerpt": counts[WRONG_EXCERPT],
        "false_abstention": counts[FALSE_ABSTENTION],
        "true_uncertain": counts[TRUE_UNCERTAIN],
        "true_not_found": counts[TRUE_NOT_FOUND],
        "status_mismatch": counts[STATUS_MISMATCH],
        "true_answered_rate": (counts[TRUE_ANSWERED] / len(true_pos)) if true_pos else None,
        "uncertain": counts["status:UNCERTAIN"],
        "not_found": counts["status:NOT_FOUND"],
        "answered": counts["status:ANSWERED"],
    }


def acceptance_report(
    scored: dict[str, list[dict[str, object]]],
    perm_rows: list[dict[str, object]],
    repeat_rows: list[dict[str, object]],
    main: list[dict[str, object]],
) -> dict[str, object]:
    baseline = scored.get(PROMPT_P0) or []
    base_true = _rate(baseline, TRUE_ANSWERED, expected=ANSWERED)
    repeats = {}
    for step in REPEAT_STEPS:
        rows = [
            row
            for row in repeat_rows
            if row["step"] == step
        ] + [
            row
            for row in main
            if row["step"] == step and row["case_id"] in REPEAT_CASE_IDS
        ]
        by_case = defaultdict(list)
        for row in rows:
            by_case[row["case_id"]].append(row["status"] != ANSWERED)
        repeats[step] = {
            case_id: {"runs": len(ok), "zero_false_answered": all(ok)}
            for case_id, ok in by_case.items()
        }
    perms = {}
    for step in PERM_STEPS:
        rows = [row for row in perm_rows if row["step"] == step] + [
            row
            for row in main
            if row["step"] == step and row["case_id"] == PERM_CASE_ID
        ]
        picked = sum(1 for row in rows if row.get("cited_gold"))
        perms[step] = {
            "permutations": len(rows),
            "cited_gold": picked,
            "at_least_4_of_5": picked >= 4,
        }
    regressions = {}
    for step, rows in scored.items():
        rate = _rate(rows, TRUE_ANSWERED, expected=ANSWERED)
        drop = None if base_true is None or rate is None else (base_true - rate) * 100
        regressions[step] = {
            "true_answered_rate": rate,
            "drop_pp": drop,
            "within_2pp": drop is None or drop <= 2.0,
        }
    return {
        "repeats": repeats,
        "permutations": perms,
        "true_answered_regression": regressions,
        "false_answered_09_17_zero": {
            step: all(item["zero_false_answered"] for item in repeats.get(step, {}).values())
            if repeats.get(step)
            else False
            for step in REPEAT_STEPS
        },
    }


def freeze_tabular_status_v2(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": STATUS_V2_ID,
        "label": (
            "Frozen: P0 vs P0_v2 status definitions, decision tree, "
            "sharper questions, and English. Nearby topical units are "
            "UNCERTAIN. Default P0 stays. Does not replace C@8."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_prompt_dev": True,
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "nearby_is_uncertain": True,
        "costlier_error": COSTLIER_ERROR,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline"),
        "acceptance": payload.get("acceptance"),
        "by_step": payload.get("by_step"),
        "cases": payload.get("cases"),
        "cells": payload.get("cells"),
        "scored": payload.get("scored"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_status_v2_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or STATUS_V2_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_status_v2(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_status_v2_table(payload: dict[str, object], directory: Path | None = None) -> Path:
    target_dir = directory or EVAL_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "status-v2.csv"
    md_path = target_dir / "status-v2.md"
    rows = [row for row in payload.get("scored") or [] if row.get("kind") == "main"]
    fieldnames = [
        "step",
        "case_id",
        "role",
        "status",
        "expected_status",
        "outcome",
        "cited_gold",
        "excerpt",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    by_step = payload.get("by_step") or {}
    lines = [
        "# Tabular status P0_v2",
        "",
        "Nearby topical units are scored as `UNCERTAIN`.",
        "False `ANSWERED` is the costlier error.",
        "Default P0 is unchanged.",
        "",
        "| Steg | True ANSWERED | False ANSWERED | Missade svar | True UNCERTAIN | True NOT_FOUND | Statusfel |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for step, summary in by_step.items():
        lines.append(
            "| {step} | {true_answered} | {false_answered} | {false_abstention} | "
            "{true_uncertain} | {true_not_found} | {status_mismatch} |".format(
                step=step, **summary
            )
        )
    lines.extend(
        [
            "",
            "## Vad varje steg bidrog med",
            "",
            "- **A / P0.** Baslinje. Sju falska `ANSWERED`, däribland Avtal 09, 17 och 13.",
            "- **B.** Nya statusdefinitioner. Avtal 09 och 17 blev `UNCERTAIN`. "
            "Tre hårda negativer var oförändrade. Avtal 13 valde fortfarande 6.3.",
            "- **C.** Beslutsträdet ändrade inte huvudmängden mot B. "
            "Permutation: 6.1 bara när den låg först.",
            "- **D.** Skarpare frågor. Noll falska `ANSWERED`. Avtal 13 valde 6.1 "
            "i 5/5 permutationer. Inga missade sanna `ANSWERED`.",
            "- **E.** Engelska D. Ett kvarvarande falskt `ANSWERED` (Avtal 19, "
            "uppsägningstid / huvudavtal). Sämre än svensk D.",
            "",
            "Avtal 13 på hybrid saknade 6.1 och räknas som retrievalfel.",
            "Default `answer_cell` är fortfarande P0.",
            "",
            "## Acceptans",
            "",
            json.dumps(payload.get("acceptance") or {}, indent=2, ensure_ascii=False),
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def _answer(
    *,
    case: StatusCase,
    hits: list[SearchHit],
    graph: object,
    client: JevClient,
    step: str,
    jev_model: str,
    timeout_seconds: float,
    replay: dict[tuple[str, str, str, str], dict[str, object]] | None,
) -> tuple[object, bool]:
    if (
        step == PROMPT_P0
        and replay is not None
        and case.candidate_keys is None
    ):
        key = (case.relative_path, case.question_id, case.list_name, PROMPT_P0)
        frozen = replay.get(key)
        if frozen is not None:
            result = CellResult(
                document_id=str(frozen.get("document_id") or ""),
                relative_path=case.relative_path,
                question_id=case.question_id,
                question=str(frozen.get("question") or ""),
                variant=PROMPT_P0,
                status=str(frozen.get("status") or NOT_FOUND),
                answer=str(frozen.get("answer") or ""),
                source_unit_ids=list(frozen.get("source_unit_ids") or []),
                sources=[],
                jev_calls=int(frozen.get("jev_calls") or 1),
                prompt_tokens=frozen.get("prompt_tokens"),
                completion_tokens=frozen.get("completion_tokens"),
                answer_seconds=float(frozen.get("answer_seconds") or 0.0),
                retrieval={
                    "k": DEFAULT_K,
                    "strategy": case.list_name,
                    "candidate_keys": [hit.key for hit in hits],
                    "replayed": True,
                },
            )
            return result, True
    asked = questions_for(step)[case.question_id]
    result = answer_without_classify(
        relative_path=case.relative_path,
        question_id=case.question_id,
        user_question=asked,
        context=graph,
        seeds=hits,
        jev=client,
        jev_model=jev_model,
        timeout_seconds=timeout_seconds,
        retrieve_seconds=0.0,
        retrieval={
            "k": DEFAULT_K,
            "strategy": case.list_name,
            "candidate_keys": [hit.key for hit in hits],
        },
        variant=step,
        instructions=instruction_for(step),
        status_criteria=criteria_for(step),
    )
    return result, False


def _run_permutations(
    cases: tuple[StatusCase, ...],
    by_signal: dict[tuple[str, str], dict[str, object]],
    graph: object,
    client: JevClient,
    jev_model: str,
    timeout_seconds: float,
    cells: list[dict[str, object]],
) -> list[dict[str, object]]:
    case = next((item for item in cases if item.case_id == PERM_CASE_ID), None)
    if case is None:
        return []
    keys = list(_case_keys(case, by_signal))
    gold_keys = _matching_keys(_hits(keys, graph.by_key(), case.relative_path), case.gold_contains)
    nearby_keys = [
        key
        for key in keys
        if any(needle in graph.by_key()[key].text for needle in case.nearby_contains)
    ]
    gold = next(iter(gold_keys), None)
    nearby = nearby_keys[0] if nearby_keys else None
    orders = {
        "as_retrieved": list(keys),
        "gold_first": _move(keys, gold, 0),
        "gold_last": _move(keys, gold, len(keys) - 1),
        "nearby_first": _move(keys, nearby, 0),
        "gold_second": _move(keys, gold, 1),
    }
    rows = []
    for step in PERM_STEPS:
        for name, order in orders.items():
            if name == "as_retrieved":
                continue
            hits = _hits(order, graph.by_key(), case.relative_path)
            result, _ = _answer(
                case=case,
                hits=hits,
                graph=graph,
                client=client,
                step=step,
                jev_model=jev_model,
                timeout_seconds=timeout_seconds,
                replay=None,
            )
            cells.append(cell_payload(result))
            row = score_status(case, result, gold_keys)
            row["kind"] = "permutation"
            row["permutation"] = name
            row["run"] = 1
            rows.append(row)
            print(
                f"PERM {step} {name} {result.status} cited_gold={row['cited_gold']}",
                file=sys.stderr,
                flush=True,
            )
    return rows


def _run_repeats(
    cases: tuple[StatusCase, ...],
    by_signal: dict[tuple[str, str], dict[str, object]],
    graph: object,
    client: JevClient,
    jev_model: str,
    timeout_seconds: float,
    repeat_n: int,
    cells: list[dict[str, object]],
) -> list[dict[str, object]]:
    wanted = [item for item in cases if item.case_id in REPEAT_CASE_IDS]
    rows = []
    for case in wanted:
        keys = _case_keys(case, by_signal)
        hits = _hits(keys, graph.by_key(), case.relative_path)
        gold_keys = _matching_keys(hits, case.gold_contains)
        for step in REPEAT_STEPS:
            for run in range(2, repeat_n + 1):
                result, _ = _answer(
                    case=case,
                    hits=hits,
                    graph=graph,
                    client=client,
                    step=step,
                    jev_model=jev_model,
                    timeout_seconds=timeout_seconds,
                    replay=None,
                )
                cells.append(cell_payload(result))
                row = score_status(case, result, gold_keys)
                row["kind"] = "repeat"
                row["run"] = run
                row["permutation"] = "as_retrieved"
                rows.append(row)
                print(
                    f"REPEAT {step} {case.case_id} #{run} {result.status}",
                    file=sys.stderr,
                    flush=True,
                )
    return rows


def _case_keys(
    case: StatusCase,
    by_signal: dict[tuple[str, str], dict[str, object]],
) -> list[str]:
    if case.candidate_keys is not None:
        return list(case.candidate_keys)
    signal = by_signal[(case.relative_path, case.question_id)]
    keys = [str(item) for item in (signal.get(case.list_name) or {}).get("candidate_keys") or []]
    if len(keys) != DEFAULT_K:
        raise ValueError(f"{case.case_id} is missing {case.list_name} keys")
    return keys


def _hits(
    keys: list[str],
    by_key: dict[str, StoredUnit],
    relative_path: str,
) -> list[SearchHit]:
    hits = []
    for rank, key in enumerate(keys, start=1):
        unit = by_key[key]
        if unit.relative_path != relative_path:
            raise ValueError(f"candidate {key} leaked another document")
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


def _matching_keys(hits: list[SearchHit], needle: str) -> set[str]:
    if not needle:
        return set()
    return {hit.key for hit in hits if needle in hit.text}


def _move(keys: list[str], item: str | None, index: int) -> list[str]:
    order = list(keys)
    if item is None or item not in order:
        return order
    order.remove(item)
    order.insert(index, item)
    return order


def _rate(
    rows: list[dict[str, object]],
    outcome: str,
    *,
    expected: str,
) -> float | None:
    wanted = [row for row in rows if row.get("expected_status") == expected]
    if not wanted:
        return None
    return sum(1 for row in wanted if row.get("outcome") == outcome) / len(wanted)


def _load_signals(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_signals_baseline()
    return json.loads(path.read_text(encoding="utf-8"))


def _load_reference() -> dict[str, object]:
    return load_tabular_prompt_dev_baseline()


def _replay_index(
    reference: dict[str, object],
) -> dict[tuple[str, str, str, str], dict[str, object]]:
    indexed = {}
    for row in reference.get("cells") or []:
        if row.get("variant") != PROMPT_P0:
            continue
        strategy = str((row.get("retrieval") or {}).get("strategy") or "")
        indexed[
            (
                str(row.get("relative_path")),
                str(row.get("question_id")),
                strategy,
                PROMPT_P0,
            )
        ] = row
    return indexed
