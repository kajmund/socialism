"""Same dense k=5 seeds. Text vs stored headings. One answer_cell each."""

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
from overgraph_ingest.tabular.contract import ANSWERED
from overgraph_ingest.tabular.enrich_dev import (
    DEV_DOCUMENTS,
    RESERVED_DOCUMENTS,
    development_cell_map,
)
from overgraph_ingest.tabular.gold import QUESTION_IDS, USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import CountingJev, P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.present import unit_heading
from overgraph_ingest.tabular.present_eval import PRESENT_ID
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.run import DEFAULT_DB, _encode_questions, _load_context
from overgraph_ingest.tabular.search import DEFAULT_K, document_local_ranks
from overgraph_ingest.tabular.evaluate import FALSE_ANSWER
from overgraph_ingest.tabular.serialize import cell_payload
from overgraph_ingest.tabular.user_eval import score_user_cell, summarize_user_scores
from overgraph_ingest.tabular.user_gold import (
    CELL_MAY_HAVE_MULTIPLE_ANSWERS,
    SILENT,
    UserCellGold,
)

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
PRESENT_RUN_ID = "phase2-tabular-present-run-v1"
PRESENT_RUN_PATH = ROOT / "baselines" / f"{PRESENT_RUN_ID}.json"
TEXT = "text"
PRESENT = "present"
SPECS = (
    (TEXT, False),
    (PRESENT, True),
)


def run_tabular_present(
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
    documents: tuple[str, ...] = DEV_DOCUMENTS,
    question_ids: tuple[str, ...] = QUESTION_IDS,
    golds: dict[tuple[str, str], UserCellGold] | None = None,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("present must use unchanged P0")
    if set(documents) & set(RESERVED_DOCUMENTS):
        raise ValueError("present run must not use the reserved holdout")
    gold_map = golds or development_cell_map()
    graph = context or _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    missing = [path for path in documents if path not in {unit.relative_path for unit in graph.units}]
    if missing:
        raise ValueError(f"development documents missing from current ingest: {missing}")
    encoded = queries or _encode_questions(
        db_path=db_path or DEFAULT_DB,
        dense_dimension=dense_dimension,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        dense_model=dense_model,
        units=graph.units,
    )
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for present text vs metadata")
    client = jev if isinstance(jev, CountingJev) else CountingJev(
        jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    )
    by_key = graph.by_key()
    started = time.perf_counter()
    cells: list[dict[str, object]] = []
    scored: dict[str, list[dict[str, object]]] = {TEXT: [], PRESENT: []}
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
            seeds = ranks["dense"][:DEFAULT_K]
            retrieve_seconds = time.perf_counter() - retrieve_started
            candidate_keys = [hit.key for hit in seeds]
            headings = heading_bindings(seeds, by_key, graph.structures)
            retrieval = {
                "k": DEFAULT_K,
                "strategy": "dense",
                "candidate_keys": candidate_keys,
                "headings": headings,
            }
            for name, present in SPECS:
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
                    present_structure=present,
                )
                payload = cell_payload(result)
                payload["excerpt_in_evidence"] = excerpt_in_evidence(payload, by_key)
                payload["heading_cited"] = heading_cited(payload, headings, by_key)
                cells.append(payload)
                scored[name].append(score_user_cell(payload, gold))
                print(
                    f"{name} {result.document_id} {question_id} {result.status}",
                    file=sys.stderr,
                    flush=True,
                )
    summaries = {name: summarize_user_scores(rows) for name, rows in scored.items()}
    paired = pair_present(scored[TEXT], scored[PRESENT], cells)
    return {
        "operation": "tabular_present_run",
        "experiment": PRESENT_RUN_ID,
        "gold_id": PRESENT_ID,
        "same_mapping": GOLD_MAP_VERSION,
        "does_not_change_ingest": True,
        "does_not_change_embeddings": True,
        "does_not_change_retrieval": True,
        "does_not_change_default_prompt": True,
        "does_not_run_c": True,
        "does_not_run_cerebras": True,
        "original_embeddings_stay": True,
        "search_is_not_evidence": True,
        "headings_are_not_excerpts": True,
        "same_five_units": True,
        "one_jev_call": True,
        "reserved_unused": True,
        "default_remains_d": True,
        "e_is_next_candidate": True,
        "performance_reference": VARIANT_E,
        "strategy": "dense",
        "k": DEFAULT_K,
        "user_question_is_the_contract": True,
        "cell_may_have_multiple_answers": CELL_MAY_HAVE_MULTIPLE_ANSWERS,
        "documents": list(documents),
        "cells_expected": len(documents) * len(question_ids) * len(SPECS),
        "cells": cells,
        "scored": scored,
        "paired": paired,
        "variants": {
            name: {"variant": name, "present_structure": present, "summary": summaries[name]}
            for name, present in SPECS
        },
        "headline": {
            name: {
                "full_success_rate": summaries[name]["full_success_rate"],
                "polarity": summaries[name]["polarity"],
            }
            for name in summaries
        },
        "decision": decide_present(summaries, paired),
        "wall_seconds": time.perf_counter() - started,
        "jev_calls": sum(int(cell.get("jev_calls") or 0) for cell in cells),
        "heading_cited": sum(1 for cell in cells if cell.get("heading_cited")),
        "excerpt_outside_evidence": sum(
            1 for cell in cells if cell.get("excerpt_in_evidence") is False
        ),
    }


def heading_bindings(
    seeds,
    by_key: dict[str, StoredUnit],
    structures: dict[str, dict[str, object]],
) -> dict[str, dict[str, str]]:
    bindings: dict[str, dict[str, str]] = {}
    for hit in seeds:
        unit = by_key[hit.key]
        structure = structures.get(unit.structure_id, {})
        bindings[unit.key] = {
            "structure_id": unit.structure_id,
            "heading": unit_heading(structure),
        }
    return bindings


def excerpt_in_evidence(cell: dict[str, object], by_key: dict[str, StoredUnit]) -> bool | None:
    if cell.get("status") != ANSWERED:
        return None
    for source in cell.get("sources") or []:
        if not isinstance(source, dict):
            continue
        unit = by_key.get(str(source.get("unit_id") or ""))
        excerpt = str(source.get("excerpt") or "")
        if unit is None or excerpt not in unit.text:
            return False
    return True


def heading_cited(
    cell: dict[str, object],
    headings: dict[str, dict[str, str]],
    by_key: dict[str, StoredUnit],
) -> bool:
    if cell.get("status") != ANSWERED:
        return False
    for source in cell.get("sources") or []:
        if not isinstance(source, dict):
            continue
        excerpt = str(source.get("excerpt") or "")
        unit_id = str(source.get("unit_id") or "")
        heading = headings.get(unit_id, {}).get("heading") or ""
        unit = by_key.get(unit_id)
        if heading and excerpt == heading and unit is not None and excerpt not in unit.text:
            return True
    return False


def pair_present(
    text_rows: list[dict[str, object]],
    present_rows: list[dict[str, object]],
    cells: list[dict[str, object]],
) -> dict[str, object]:
    text_cells = {
        (str(cell["relative_path"]), str(cell["question_id"])): cell
        for cell in cells
        if cell.get("variant") == TEXT
    }
    present_cells = {
        (str(cell["relative_path"]), str(cell["question_id"])): cell
        for cell in cells
        if cell.get("variant") == PRESENT
    }
    by_present = {
        (str(row["relative_path"]), str(row["question_id"])): row for row in present_rows
    }
    rows = []
    for text in text_rows:
        key = (str(text["relative_path"]), str(text["question_id"]))
        present = by_present[key]
        same_keys = (
            text_cells[key]["retrieval"]["candidate_keys"]
            == present_cells[key]["retrieval"]["candidate_keys"]
        )
        if not same_keys:
            raise ValueError(f"present changed retrieval for {key}")
        changed = (
            text["outcome"] != present["outcome"]
            or text["status"] != present["status"]
            or text_cells[key].get("answer") != present_cells[key].get("answer")
        )
        rows.append(
            {
                "relative_path": key[0],
                "question_id": key[1],
                "polarity": text["polarity"],
                "text_status": text["status"],
                "present_status": present["status"],
                "text_outcome": text["outcome"],
                "present_outcome": present["outcome"],
                "text_success": text["full_success"],
                "present_success": present["full_success"],
                "changed": changed,
                "lost_positive": (
                    text["polarity"] != SILENT and text["full_success"] and not present["full_success"]
                ),
                "new_false_positive": (
                    present["outcome"] == FALSE_ANSWER and text["outcome"] != FALSE_ANSWER
                ),
                "fixed_false_positive": (
                    text["outcome"] == FALSE_ANSWER and present["outcome"] != FALSE_ANSWER
                ),
            }
        )
    return {
        "cells": len(rows),
        "changed": sum(1 for row in rows if row["changed"]),
        "lost_positive": sum(1 for row in rows if row["lost_positive"]),
        "new_false_positive": sum(1 for row in rows if row["new_false_positive"]),
        "fixed_false_positive": sum(1 for row in rows if row["fixed_false_positive"]),
        "rows": rows,
    }


def decide_present(
    summaries: dict[str, dict[str, object]],
    paired: dict[str, object],
) -> dict[str, object]:
    text = summaries[TEXT]["polarity"]
    present = summaries[PRESENT]["polarity"]
    fewer_false = present["negative_false_answer"] < text["negative_false_answer"]
    kept_positive = present["positive_correct"] >= text["positive_correct"]
    return {
        "fewer_silent_false_and_kept_positives": fewer_false and kept_positive,
        "do_not_add_more_metadata_fields": True,
        "do_not_run_reserved_holdout": True,
        "do_not_switch_default": True,
        "default_remains_d": True,
        "reason": (
            "Presentation evidence only. Do not add more metadata fields "
            "to move the numbers. Reserved holdout stays unused."
        ),
    }


def freeze_present_run(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PRESENT_RUN_ID,
        "label": (
            "Dense k=5 text vs stored headings on development cells. "
            "Same five units. P0. One Jev. Headings are not excerpts."
        ),
        "do_not_overwrite": True,
        "does_not_change_retrieval": True,
        "does_not_change_embeddings": True,
        "same_five_units": True,
        "one_jev_call": True,
        "headings_are_not_excerpts": True,
        "reserved_unused": True,
        "default_remains_d": True,
        "strategy": payload.get("strategy"),
        "documents": payload.get("documents"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "paired": {
            key: payload["paired"][key]
            for key in (
                "cells",
                "changed",
                "lost_positive",
                "new_false_positive",
                "fixed_false_positive",
            )
        },
        "paired_rows": payload["paired"]["rows"],
        "variants": {
            name: variant["summary"] for name, variant in payload["variants"].items()
        },
        "scored": payload.get("scored"),
        "cells": payload.get("cells"),
        "jev_calls": payload.get("jev_calls"),
        "heading_cited": payload.get("heading_cited"),
        "excerpt_outside_evidence": payload.get("excerpt_outside_evidence"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_present_run_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PRESENT_RUN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_present_run(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_present_run_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "present-run-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    paired = payload["paired"]
    lines = [
        "# Candidate presentation run",
        "",
        "Dense k=5. Same five TextUnits. P0. One Jev.",
        "Headings from stored Structure. Evidence stays original.",
        "Reserved holdout unused. Default stays D.",
        "",
        "| Variant | Full success | Positive correct | Silent stayed | False on silent |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in (TEXT, PRESENT):
        summary = payload["variants"][name]["summary"]
        split = summary["polarity"]
        lines.append(
            "| {name} | {full:.0%} ({ok}/{n}) | {pos:.0%} ({pc}/{p}) | "
            "{neg:.0%} ({ns}/{q}) | {false} |".format(
                name=name,
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
    lines.extend(
        [
            "",
            f"Changed cells: {paired['changed']}/{paired['cells']}.",
            f"Lost previously correct positives: {paired['lost_positive']}.",
            f"New false positives: {paired['new_false_positive']}.",
            f"Fixed false positives: {paired['fixed_false_positive']}.",
            f"Heading cited as evidence: {payload['heading_cited']}.",
            f"Excerpt outside original text: {payload['excerpt_outside_evidence']}.",
            "",
            (
                "PRESENT did not reduce silent false answers and lost "
                "one previously correct positive."
                if not payload["decision"]["fewer_silent_false_and_kept_positives"]
                else "PRESENT reduced silent false answers without losing correct positives."
            ),
            "",
            payload["decision"]["reason"],
            "",
            "## What this is not",
            "",
            "- Not a retrieval change.",
            "- Not a new embedding.",
            "- Not more metadata fields.",
            "- Not the reserved holdout.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
