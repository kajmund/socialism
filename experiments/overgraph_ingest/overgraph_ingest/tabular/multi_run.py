"""Same dense k=5 seeds. One cell answer vs a list. One Jev call each."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.cells import VARIANT_E, answer_without_classify
from overgraph_ingest.tabular.enrich_dev import RESERVED_DOCUMENTS, development_cell_map
from overgraph_ingest.tabular.gold import QUESTION_IDS, USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import CountingJev, MULTI_SLOTS, P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.multi_eval import (
    MULTI_ID,
    decide_multi,
    multi_documents,
    review_multi_protocol,
    score_multi_cell,
    summarize_multi_scores,
)
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.run import DEFAULT_DB, _encode_questions, _load_context
from overgraph_ingest.tabular.search import DEFAULT_K, document_local_ranks
from overgraph_ingest.tabular.serialize import cell_payload
from overgraph_ingest.tabular.user_gold import (
    CELL_MAY_HAVE_MULTIPLE_ANSWERS,
    UserCellGold,
)

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
MULTI_RUN_ID = "phase2-tabular-multi-run-v1"
MULTI_RUN_PATH = ROOT / "baselines" / f"{MULTI_RUN_ID}.json"
SINGLE = "single"
MULTI = "multi"
SPECS = (
    (SINGLE, False),
    (MULTI, True),
)


def run_tabular_multi(
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
    documents: tuple[str, ...] | None = None,
    question_ids: tuple[str, ...] = QUESTION_IDS,
    golds: dict[tuple[str, str], UserCellGold] | None = None,
) -> dict[str, object]:
    protocol = review_multi_protocol()
    chosen = documents if documents is not None else tuple(protocol["documents"])
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("multi single path must keep P0")
    if set(chosen) & set(RESERVED_DOCUMENTS):
        raise ValueError("multi run must not use the reserved holdout")
    gold_map = golds or development_cell_map()
    graph = context or _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    missing = [path for path in chosen if path not in {unit.relative_path for unit in graph.units}]
    if missing:
        raise ValueError(f"multi documents missing from current ingest: {missing}")
    encoded = queries or _encode_questions(
        db_path=db_path or DEFAULT_DB,
        dense_dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        dense_model=dense_model,
        units=graph.units,
    )
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for multi single vs list")
    client = jev if isinstance(jev, CountingJev) else CountingJev(
        jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    )
    started = time.perf_counter()
    cells: list[dict[str, object]] = []
    scored: dict[str, list[dict[str, object]]] = {SINGLE: [], MULTI: []}
    for relative_path in chosen:
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
            seeds = ranks["dense"][:DEFAULT_K]
            retrieve_seconds = time.perf_counter() - retrieve_started
            retrieval = {
                "k": DEFAULT_K,
                "strategy": "dense",
                "candidate_keys": [hit.key for hit in seeds],
            }
            for name, multi in SPECS:
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
                    variant=name,
                    multi_answers=multi,
                )
                payload = cell_payload(result)
                payload["answers"] = [
                    {
                        "excerpt": source["excerpt"],
                        "unit_id": source["unit_id"],
                        "clause_number": source["clause_number"],
                    }
                    for source in payload["sources"]
                    if isinstance(source, dict)
                ]
                payload["answer_count"] = len(payload["answers"])
                cells.append(payload)
                scored[name].append(score_multi_cell(payload, gold))
                print(
                    f"{name} {result.document_id} {question_id} {result.status} "
                    f"n={payload['answer_count']}",
                    file=sys.stderr,
                    flush=True,
                )
    summaries = {name: summarize_multi_scores(rows) for name, rows in scored.items()}
    paired = pair_multi(scored[SINGLE], scored[MULTI], cells)
    return {
        "operation": "tabular_multi_run",
        "experiment": MULTI_RUN_ID,
        "gold_id": MULTI_ID,
        "same_mapping": GOLD_MAP_VERSION,
        "does_not_change_ingest": True,
        "does_not_change_embeddings": True,
        "does_not_change_retrieval": True,
        "does_not_change_default_prompt": True,
        "does_not_present_headings": True,
        "does_not_run_c": True,
        "does_not_run_reserved_holdout": True,
        "same_five_units": True,
        "one_jev_call": True,
        "slots": MULTI_SLOTS,
        "default_remains_d": True,
        "e_is_experimental_candidate": True,
        "performance_reference": VARIANT_E,
        "strategy": "dense",
        "k": DEFAULT_K,
        "cell_may_have_multiple_answers": CELL_MAY_HAVE_MULTIPLE_ANSWERS,
        "do_not_start_product_from_this_run": True,
        "documents": list(chosen),
        "cells_expected": len(chosen) * len(question_ids) * len(SPECS),
        "cells": cells,
        "scored": scored,
        "paired": paired,
        "variants": {
            name: {"variant": name, "multi_answers": multi, "summary": summaries[name]}
            for name, multi in SPECS
        },
        "headline": summaries,
        "decision": decide_multi(summaries, SINGLE, MULTI),
        "wall_seconds": time.perf_counter() - started,
        "jev_calls": sum(int(cell.get("jev_calls") or 0) for cell in cells),
    }


def pair_multi(
    single_rows: list[dict[str, object]],
    multi_rows: list[dict[str, object]],
    cells: list[dict[str, object]],
) -> dict[str, object]:
    single_cells = {
        (str(cell["relative_path"]), str(cell["question_id"])): cell
        for cell in cells
        if cell.get("variant") == SINGLE
    }
    multi_cells = {
        (str(cell["relative_path"]), str(cell["question_id"])): cell
        for cell in cells
        if cell.get("variant") == MULTI
    }
    by_multi = {
        (str(row["relative_path"]), str(row["question_id"])): row for row in multi_rows
    }
    rows = []
    for single in single_rows:
        key = (str(single["relative_path"]), str(single["question_id"]))
        multi = by_multi[key]
        same_keys = (
            single_cells[key]["retrieval"]["candidate_keys"]
            == multi_cells[key]["retrieval"]["candidate_keys"]
        )
        if not same_keys:
            raise ValueError(f"multi changed retrieval for {key}")
        rows.append(
            {
                "relative_path": key[0],
                "question_id": key[1],
                "multi_gold": single["multi_gold"],
                "single_status": single["status"],
                "multi_status": multi["status"],
                "single_gold_hits": single["gold_hits"],
                "multi_gold_hits": multi["gold_hits"],
                "single_extra_n": single["extra_n"],
                "multi_extra_n": multi["extra_n"],
                "single_predicted_n": single["predicted_n"],
                "multi_predicted_n": multi["predicted_n"],
                "changed": (
                    single["gold_hits"] != multi["gold_hits"]
                    or single["extra_n"] != multi["extra_n"]
                    or single["status"] != multi["status"]
                ),
                "more_gold": multi["gold_hits"] > single["gold_hits"],
                "more_extras": multi["extra_n"] > single["extra_n"],
            }
        )
    return {
        "cells": len(rows),
        "changed": sum(1 for row in rows if row["changed"]),
        "more_gold": sum(1 for row in rows if row["more_gold"]),
        "more_extras": sum(1 for row in rows if row["more_extras"]),
        "rows": rows,
    }


def freeze_multi_run(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": MULTI_RUN_ID,
        "label": (
            "Dense k=5 one cell answer vs a list of independent answers. "
            "Same five units. One Jev. Extras are not quality."
        ),
        "do_not_overwrite": True,
        "does_not_change_retrieval": True,
        "same_five_units": True,
        "one_jev_call": True,
        "does_not_run_reserved_holdout": True,
        "default_remains_d": True,
        "do_not_start_product_from_this_run": True,
        "slots": payload.get("slots"),
        "strategy": payload.get("strategy"),
        "documents": payload.get("documents"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "paired": {
            key: payload["paired"][key]
            for key in ("cells", "changed", "more_gold", "more_extras")
        },
        "paired_rows": payload["paired"]["rows"],
        "variants": {
            name: variant["summary"] for name, variant in payload["variants"].items()
        },
        "scored": payload.get("scored"),
        "cells": payload.get("cells"),
        "jev_calls": payload.get("jev_calls"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_multi_run_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or MULTI_RUN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_multi_run(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_multi_run_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "multi-run-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Multiple answers per cell",
        "",
        "Dense k=5. Same five TextUnits. One Jev.",
        "Single keeps P0. Multi lists distinct listed excerpts.",
        "Reserved holdout unused. Default stays D.",
        "",
        "| Variant | Gold hits | Extras | Multi-span hits | Multi-span extras |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in (SINGLE, MULTI):
        summary = payload["variants"][name]["summary"]
        lines.append(
            "| {name} | {hits}/{gold} | {extra} | {mhits}/{mgold} | {mextra} |".format(
                name=name,
                hits=summary["gold_hits"],
                gold=summary["gold_n"],
                extra=summary["extra_n"],
                mhits=summary["multi_gold_hits"],
                mgold=summary["multi_gold_n"],
                mextra=summary["multi_extra_n"],
            )
        )
    paired = payload["paired"]
    lines.extend(
        [
            "",
            f"Changed cells: {paired['changed']}/{paired['cells']}.",
            f"Cells with more gold hits: {paired['more_gold']}.",
            f"Cells with more extras: {paired['more_extras']}.",
            "",
            (
                "Jev can return several cited answers in one call. "
                "On multi-span cells it found more gold, and it also "
                "added extras. That is not an unfiltered quality win."
            ),
            "",
            payload["decision"]["reason"],
            "",
            "## What this is not",
            "",
            "- Not a retrieval change.",
            "- Not heading metadata.",
            "- Not the reserved holdout.",
            "- Not the Socialism product table.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
