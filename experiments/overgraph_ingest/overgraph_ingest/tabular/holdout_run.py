"""Holdout D/E/K on current ingest. One answer_cell. No structural change."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.cells import VARIANT_D, VARIANT_E, VARIANT_K, answer_without_classify
from overgraph_ingest.tabular.gold import QUESTION_IDS, USER_QUESTIONS
from overgraph_ingest.tabular.holdout import HOLD_OUT_DOCUMENTS, HOLD_OUT_ID
from overgraph_ingest.tabular.holdout_gold import UserCellGold, holdout_cell_map
from overgraph_ingest.tabular.jev_io import CountingJev, P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.run import DEFAULT_DB, _encode_questions, _load_context
from overgraph_ingest.tabular.search import DEFAULT_K, document_local_ranks
from overgraph_ingest.tabular.serialize import cell_payload
from overgraph_ingest.tabular.user_eval import score_user_cell, summarize_user_scores
from overgraph_ingest.tabular.user_gold import CELL_MAY_HAVE_MULTIPLE_ANSWERS

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
HOLD_OUT_RUN_ID = "phase2-tabular-holdout-run-v1"
HOLD_OUT_RUN_PATH = ROOT / "baselines" / f"{HOLD_OUT_RUN_ID}.json"
K10 = 10
HOLD_OUT_SPECS = (
    (VARIANT_D, "hybrid", DEFAULT_K),
    (VARIANT_E, "dense", DEFAULT_K),
    (VARIANT_K, "hybrid", K10),
)


def run_tabular_holdout(
    *,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    dense_model: str = "text-embedding-3-large",
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]] | None = None,
    jev: JevClient | None = None,
    context: GraphContext | None = None,
    documents: tuple[str, ...] = HOLD_OUT_DOCUMENTS,
    question_ids: tuple[str, ...] = QUESTION_IDS,
    golds: dict[tuple[str, str], UserCellGold] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("holdout must use unchanged P0")
    gold_map = golds or holdout_cell_map()
    graph = context or _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    _require_documents(graph.units, documents)
    encoded = queries or _encode_questions(
        db_path=db_path or DEFAULT_DB,
        dense_dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        dense_model=dense_model,
        units=graph.units,
    )
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for holdout D/E/K")
    client = jev if isinstance(jev, CountingJev) else CountingJev(
        jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    )
    started = time.perf_counter()
    cells: list[dict[str, object]] = []
    scored: dict[str, list[dict[str, object]]] = {name: [] for name, _, _ in HOLD_OUT_SPECS}
    for relative_path in documents:
        for question_id in question_ids:
            gold = gold_map[(relative_path, question_id)]
            dense_query, sparse_query = encoded[question_id]
            retrieve_started = time.perf_counter()
            ranks = document_local_ranks(
                graph.units,
                relative_path,
                dense_query=dense_query,
                sparse_query=sparse_query,
            )
            retrieve_seconds = time.perf_counter() - retrieve_started
            for variant, strategy, top_k in HOLD_OUT_SPECS:
                seeds = ranks[strategy][:top_k]
                retrieval = {
                    "k": top_k,
                    "strategy": strategy,
                    "candidate_keys": [hit.key for hit in seeds],
                }
                result = answer_without_classify(
                    relative_path=relative_path,
                    question_id=question_id,
                    user_question=USER_QUESTIONS[question_id],
                    context=graph,
                    seeds=seeds,
                    jev=client,
                    jev_model=jev_model,
                    timeout_seconds=jev_timeout_seconds,
                    retrieve_seconds=retrieve_seconds,
                    retrieval=retrieval,
                    variant=variant,
                )
                payload = cell_payload(result)
                cells.append(payload)
                scored[variant].append(score_user_cell(payload, gold))
                print(
                    f"{variant} {result.document_id} {question_id} {result.status}",
                    file=sys.stderr,
                    flush=True,
                )
    summaries = {name: summarize_user_scores(rows) for name, rows in scored.items()}
    return {
        "operation": "tabular_holdout_run",
        "experiment": HOLD_OUT_RUN_ID,
        "gold_id": HOLD_OUT_ID,
        "same_mapping": GOLD_MAP_VERSION,
        "does_not_change_ingest": True,
        "does_not_change_embeddings": True,
        "does_not_run_cerebras": True,
        "does_not_run_qwen": True,
        "does_not_change_default_prompt": True,
        "does_not_change_default_hybrid": True,
        "does_not_change_default_k": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "one_jev_call": True,
        "no_classify": True,
        "no_structural_preprocess": True,
        "user_question_is_the_contract": True,
        "cell_may_have_multiple_answers": CELL_MAY_HAVE_MULTIPLE_ANSWERS,
        "documents": list(documents),
        "cells_expected": len(documents) * len(question_ids) * len(HOLD_OUT_SPECS),
        "cells": cells,
        "scored": scored,
        "variants": {
            name: {
                "variant": name,
                "strategy": strategy,
                "k": top_k,
                "summary": summaries[name],
            }
            for name, strategy, top_k in HOLD_OUT_SPECS
        },
        "headline": {
            name: {
                "full_success_rate": summaries[name]["full_success_rate"],
                "polarity": summaries[name]["polarity"],
            }
            for name in summaries
        },
        "decision": decide_holdout(summaries),
        "wall_seconds": time.perf_counter() - started,
        "jev_calls": sum(int(cell.get("jev_calls") or 0) for cell in cells),
    }


def _require_documents(units: list[StoredUnit], documents: tuple[str, ...]) -> None:
    have = {unit.relative_path for unit in units}
    missing = [path for path in documents if path not in have]
    if missing:
        raise ValueError(f"holdout documents missing from current ingest: {missing}")


def decide_holdout(summaries: dict[str, dict[str, object]]) -> dict[str, object]:
    d = summaries[VARIANT_D]["polarity"]
    e = summaries[VARIANT_E]["polarity"]
    k = summaries[VARIANT_K]["polarity"]
    e_better_positive = e["positive_correct_rate"] > d["positive_correct_rate"]
    e_not_worse_negative = e["negative_false_answer"] <= d["negative_false_answer"]
    k_better = k["positive_correct_rate"] > max(
        d["positive_correct_rate"], e["positive_correct_rate"]
    )
    return {
        "e_improves_positive_without_extra_silent_false_answers": (
            e_better_positive and e_not_worse_negative
        ),
        "k_beats_both_on_positive": k_better,
        "do_not_switch_default": True,
        "default_remains_d": True,
        "reason": (
            "Holdout evidence only. Default stays hybrid k=5 / D until "
            "the numbers are read. No ingest change."
        ),
    }


def freeze_holdout_run(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": HOLD_OUT_RUN_ID,
        "label": (
            "Holdout D/E/K on current ingest. One Jev answer_cell. "
            "P0 unchanged. No structural preprocess. Default stays D."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_change_ingest": True,
        "does_not_run_cerebras": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "one_jev_call": True,
        "no_structural_preprocess": True,
        "user_question_is_the_contract": True,
        "gold_id": payload.get("gold_id"),
        "documents": payload.get("documents"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "variants": {
            name: variant["summary"] for name, variant in payload["variants"].items()
        },
        "scored": payload.get("scored"),
        "cells": payload.get("cells"),
        "jev_calls": payload.get("jev_calls"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_holdout_run_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or HOLD_OUT_RUN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_holdout_run(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_holdout_run_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "holdout-run-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Tabular Review holdout run",
        "",
        "Current ingest. Current embeddings. P0. One Jev `answer_cell`.",
        "No structural preprocess. Default stays D.",
        "",
        "| Variant | Strategy | k | Full success | Positive correct | Negative stayed | False on silent |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for name, strategy, top_k in HOLD_OUT_SPECS:
        summary = payload["variants"][name]["summary"]
        split = summary["polarity"]
        lines.append(
            "| {name} | {strategy} | {k} | {full:.0%} ({ok}/{n}) | "
            "{pos:.0%} ({pc}/{p}) | {neg:.0%} ({ns}/{q}) | {false} |".format(
                name=name,
                strategy=strategy,
                k=top_k,
                full=summary["full_success_rate"],
                ok=summary["full_success"],
                n=summary["cells"],
                pos=split["positive_correct_rate"],
                pc=split["positive_correct"],
                p=split["positive_cells"],
                neg=split["negative_stayed_rate"],
                ns=split["negative_stayed_negative"],
                q=split["negative_cells"],
                false=split["negative_false_answer"],
            )
        )
    d = payload["variants"]["D"]["summary"]["polarity"]
    e = payload["variants"]["E"]["summary"]["polarity"]
    lines.extend(
        [
            "",
            f"{payload.get('jev_calls')} Jev calls. Same P0. Same embeddings. "
            "Gold written before models.",
            "",
            "## Reading",
            "",
            f"E recovered {e['positive_correct'] - d['positive_correct']} more "
            f"of the {e['positive_cells']} addressed cells than D "
            f"({d['positive_correct']} → {e['positive_correct']}) "
            f"and added {e['negative_false_answer'] - d['negative_false_answer']} "
            "silent false answer "
            f"({d['negative_false_answer']} → {e['negative_false_answer']}).",
            "",
            payload["decision"]["reason"],
            "",
            "## What this is not",
            "",
            "- Not a default change.",
            "- Not a new ingest.",
            "- Not Cerebras or Qwen.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
