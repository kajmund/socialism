"""Score one listed excerpt versus several. Gold spans stay the contract."""

from __future__ import annotations

from overgraph_ingest.tabular.contract import ANSWERED
from overgraph_ingest.tabular.enrich_dev import RESERVED_DOCUMENTS, development_cells
from overgraph_ingest.tabular.jev_io import MULTI_SLOTS, P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_eval import normalize, score_user_cell
from overgraph_ingest.tabular.user_gold import UserCellGold

MULTI_ID = "tabular-multi-v1"


def multi_cells() -> tuple[UserCellGold, ...]:
    return tuple(cell for cell in development_cells() if len(cell.answers) >= 2)


def multi_documents() -> tuple[str, ...]:
    documents = tuple(dict.fromkeys(cell.relative_path for cell in multi_cells()))
    if set(documents) & set(RESERVED_DOCUMENTS):
        raise ValueError("multi documents overlap the reserved holdout")
    if not documents:
        raise ValueError("multi experiment needs cells with several gold answers")
    return documents


def review_multi_protocol() -> dict[str, object]:
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("multi single path must keep P0")
    if DEFAULT_K != 5:
        raise ValueError("tabular default k must stay 5")
    if MULTI_SLOTS != 5:
        raise ValueError("multi slots must stay 5")
    cells = multi_cells()
    documents = multi_documents()
    return {
        "operation": "tabular_multi_protocol",
        "experiment": MULTI_ID,
        "does_not_change_retrieval": True,
        "does_not_change_embeddings": True,
        "does_not_change_ingest": True,
        "does_not_change_default_prompt": True,
        "does_not_add_jev_calls": True,
        "does_not_run_reserved_holdout": True,
        "does_not_present_headings": True,
        "same_five_units": True,
        "one_jev_call": True,
        "default_remains_d": True,
        "e_is_experimental_candidate": True,
        "do_not_start_product_from_this_run": True,
        "slots": MULTI_SLOTS,
        "documents": list(documents),
        "multi_cells": len(cells),
        "gold_answers_on_multi_cells": sum(len(cell.answers) for cell in cells),
        "baseline": "one cell answer",
        "treatment": "list of independent answers and sources",
    }


def predicted_excerpts(cell: dict[str, object]) -> list[str]:
    if cell.get("status") != ANSWERED:
        return []
    excerpts: list[str] = []
    for source in cell.get("sources") or []:
        if not isinstance(source, dict):
            continue
        excerpt = normalize(str(source.get("excerpt") or ""))
        if excerpt and excerpt not in excerpts:
            excerpts.append(excerpt)
    return excerpts


def score_multi_cell(cell: dict[str, object], gold: UserCellGold) -> dict[str, object]:
    row = score_user_cell(cell, gold)
    predicted = predicted_excerpts(cell)
    hits = []
    for span in gold.answers:
        needle = normalize(span.contains)
        if needle and any(needle in excerpt for excerpt in predicted):
            hits.append(span.contains)
    extras = []
    for excerpt in predicted:
        if not gold.answers or not any(
            normalize(span.contains) and normalize(span.contains) in excerpt
            for span in gold.answers
        ):
            extras.append(excerpt)
    row["gold_n"] = len(gold.answers)
    row["gold_hits"] = len(hits)
    row["matched_spans"] = hits
    row["predicted_n"] = len(predicted)
    row["extra_n"] = len(extras)
    row["extras"] = extras
    row["multi_gold"] = len(gold.answers) >= 2
    return row


def summarize_multi_scores(rows: list[dict[str, object]]) -> dict[str, object]:
    multi = [row for row in rows if row.get("multi_gold")]
    return {
        "cells": len(rows),
        "multi_cells": len(multi),
        "gold_n": sum(int(row["gold_n"]) for row in rows),
        "gold_hits": sum(int(row["gold_hits"]) for row in rows),
        "predicted_n": sum(int(row["predicted_n"]) for row in rows),
        "extra_n": sum(int(row["extra_n"]) for row in rows),
        "multi_gold_n": sum(int(row["gold_n"]) for row in multi),
        "multi_gold_hits": sum(int(row["gold_hits"]) for row in multi),
        "multi_predicted_n": sum(int(row["predicted_n"]) for row in multi),
        "multi_extra_n": sum(int(row["extra_n"]) for row in multi),
    }


def decide_multi(
    summaries: dict[str, dict[str, object]],
    single_name: str,
    multi_name: str,
) -> dict[str, object]:
    single = summaries[single_name]
    multi = summaries[multi_name]
    more_gold = multi["multi_gold_hits"] > single["multi_gold_hits"]
    not_more_extras = multi["multi_extra_n"] <= single["multi_extra_n"]
    return {
        "more_gold_hits_without_more_extras": more_gold and not_more_extras,
        "do_not_switch_default": True,
        "default_remains_d": True,
        "do_not_start_product_from_this_run": True,
        "do_not_run_reserved_holdout": True,
        "reason": (
            "Multi-answer evidence only. A model that adds extras "
            "has not improved quality. Default stays D. "
            "Do not start the Socialism table from this run."
        ),
    }
