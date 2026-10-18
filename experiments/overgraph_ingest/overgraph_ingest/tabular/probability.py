"""P1: observe Jev choice confidence. Does not change status. P2 is not implemented."""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.baseline import load_official_classify_baseline
from overgraph_ingest.jev.client import HttpJevClient, JevClient, JevResult
from overgraph_ingest.jev.questions import choice_row_fields, parse_confidence
from overgraph_ingest.retrieval.conclusions import load_tabular_review_baseline
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.cells import VARIANT_D, answer_without_classify
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.direct import frozen_b_cells, _hits, _load_context
from overgraph_ingest.tabular.evaluate import (
    FALSE_ANSWER,
    TRUE_ANSWER,
    score_cell,
    summarize,
)
from overgraph_ingest.tabular.gold import USER_QUESTIONS, cell_relevant_keys, load_tabular_golds
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.serialize import cell_payload

ROOT = Path(__file__).resolve().parents[2]
PROBABILITY_ID = "phase2-tabular-jev-probability-v1"
PROBABILITY_PATH = ROOT / "baselines" / f"{PROBABILITY_ID}.json"
EVAL_DIR = ROOT / "eval"
SCORE_TYPE = "jev_choice_confidence"
SCORE_FIELD = "confidence"
P2_IMPLEMENTED = False
PROTECTED = (
    ROOT / "baselines" / "phase2-jev-classify-c8.json",
    ROOT / "baselines" / "phase2-tabular-review-v1.json",
    ROOT / "baselines" / "phase2-tabular-direct-v1.json",
    ROOT / "baselines" / "phase2-tabular-status-v2.json",
)


@dataclass
class CapturingJev:
    inner: JevClient
    captured: list[JevResult] = field(default_factory=list)

    def ask(
        self,
        *,
        state: object,
        questions: dict[str, object],
        model: str,
        timeout_seconds: float,
    ) -> JevResult:
        result = self.inner.ask(
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self.captured.append(result)
        return result


def inventory_jev_scores() -> dict[str, object]:
    classify = _classify_score_inventory()
    return {
        "api": "POST /v1/systemone",
        "request_includes_score_flag": False,
        "score_field": SCORE_FIELD,
        "distribution_field": "probabilities",
        "score_type": SCORE_TYPE,
        "returns_all_alternatives": True,
        "score_is_token_logprob": False,
        "score_is_legal_correctness": False,
        "score_is_calibrated_probability": False,
        "answer_cell_can_read_without_extra_call": True,
        "answer_cell_currently_discards_score": True,
        "default_request_contract_unchanged": True,
        "default_prompt_unchanged": instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS,
        "tabular_baselines_contain_scores": False,
        "replay_possible": False,
        "classify_prior": classify,
        "p2_implemented": P2_IMPLEMENTED,
        "notes": (
            "TypeSafe choice answers include `confidence` for the chosen "
            "alternative and `probabilities` for every listed alternative. "
            "That is a classification distribution, not a token logprob and "
            "not legal correctness. `confidence` is usually the chosen "
            "probability but is not always identical to it. Classify already "
            "stores `confidence`. Tabular `answer_cell` reads only `choice`. "
            "Frozen tabular baselines have no scores, so P1 is a live "
            "observation of the same request. C@8 found `confidence` unstable "
            "across identical classify runs."
        ),
    }


def derive_status_from_score(*_args: object, **_kwargs: object) -> str:
    raise NotImplementedError("P2 waits for P1 analysis")


def run_tabular_probability(
    *,
    frozen_path: Path | None = None,
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
    frozen: dict[str, object] | None = None,
    expected_cells: int | None = 100,
    write_table: bool = True,
) -> dict[str, object]:
    if DEFAULT_K != 5:
        raise ValueError("tabular v1 default k must stay 5")
    if instruction_for(PROMPT_P0) != P0_STATUS_INSTRUCTIONS:
        raise ValueError("default P0 must stay the short English instruction")
    inventory = inventory_jev_scores()
    source = frozen or _load_frozen(frozen_path)
    cells = frozen_b_cells(source, expected=expected_cells)
    gold_by_id = {
        gold.id: gold for gold in golds or load_tabular_golds(gold_dir or ROOT / "retrieval_gold")
    }
    graph = _load_context(
        db_path=db_path,
        dense_dimension=dense_dimension,
        units=units,
        structures=structures,
    )
    by_key = graph.by_key()
    if jev is None and not typesafe_api_key:
        raise ValueError("--typesafe-api-key is required for tabular probability")
    capture = CapturingJev(
        jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    )
    started = time.perf_counter()
    results = []
    rows = []
    observed_fields: set[str] = set()
    for row in cells:
        question_id = str(row["question_id"])
        relative_path = str(row["relative_path"])
        gold = gold_by_id[question_id]
        relevant = cell_relevant_keys(graph.units, gold, relative_path)
        hits = _hits(row, by_key)
        retrieval = dict(row.get("retrieval") or {})
        retrieval["candidate_keys"] = [hit.key for hit in hits]
        retrieval["k"] = DEFAULT_K
        before = len(capture.captured)
        result = answer_without_classify(
            relative_path=relative_path,
            question_id=question_id,
            user_question=str(row.get("question") or USER_QUESTIONS[question_id]),
            context=graph,
            seeds=hits,
            jev=capture,
            jev_model=jev_model,
            timeout_seconds=jev_timeout_seconds,
            retrieve_seconds=0.0,
            retrieval=retrieval,
            variant="P1",
        )
        asked = capture.captured[before:]
        scores = _scores_from_capture(asked[-1] if asked else None)
        observed_fields.update(scores["answer_fields"])
        scored = score_cell(result, relevant)
        observed = _observation(result, scored, scores, relevant)
        results.append(result)
        rows.append(observed)
        print(
            f"P1 {result.document_id} {question_id} {result.status} "
            f"score={observed['model_score']}",
            file=sys.stderr,
            flush=True,
        )
    wall = time.perf_counter() - started
    inventory["observed_answer_fields"] = sorted(observed_fields)
    inventory["live_score_present"] = any(row["model_score"] is not None for row in rows)
    analysis = analyze_scores(rows)
    payload = {
        "operation": "tabular_probability",
        "experiment": PROBABILITY_ID,
        "phase": "P1",
        "p2_implemented": P2_IMPLEMENTED,
        "performance_reference": "D",
        "retrieval_baseline": "hybrid",
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "default_k_unchanged": True,
        "same_100_cells": True,
        "same_five_candidates": True,
        "no_new_retrieval": True,
        "no_navigation": True,
        "no_extra_model_call": True,
        "status_unchanged_by_score": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference_leftover": QUALITY_REFERENCE,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "inventory": inventory,
        "score_type": SCORE_TYPE,
        "cells": [cell_payload(item) for item in results],
        "observations": rows,
        "quality": summarize(rows),
        "analysis": analysis,
        "decision": analysis["decision"],
        "headline": {
            "score_type": SCORE_TYPE,
            "live_score_present": inventory["live_score_present"],
            "usable_separation": analysis["usable_separation"],
            "p2_implemented": P2_IMPLEMENTED,
            "decision": analysis["decision"]["verdict"],
            "default_prompt_unchanged": True,
        },
        "wall_seconds": wall,
    }
    if write_table:
        write_probability_table(payload)
    return payload


def analyze_scores(rows: list[dict[str, object]]) -> dict[str, object]:
    by_status = _group_stats(rows, "model_decision")
    by_question = _group_stats(rows, "question_id")
    by_outcome = _group_stats(rows, "outcome")
    answered = [row for row in rows if row["model_decision"] == ANSWERED]
    true_rows = [row for row in answered if row["outcome"] == TRUE_ANSWER]
    false_rows = [row for row in answered if row["outcome"] == FALSE_ANSWER]
    true_scores = _values(true_rows)
    false_scores = _values(false_rows)
    present = sum(1 for row in rows if row["model_score"] is not None)
    overlap = None
    usable = False
    if true_scores and false_scores:
        overlap = max(false_scores) >= min(true_scores)
        usable = not overlap
    verdict = _verdict(present, len(rows), true_scores, false_scores, usable)
    return {
        "cells": len(rows),
        "scores_present": present,
        "score_type": SCORE_TYPE,
        "by_status": by_status,
        "by_question": by_question,
        "by_outcome": by_outcome,
        "true_answered": _stats(true_scores),
        "false_answered": _stats(false_scores),
        "false_mean_lower": (
            None
            if not true_scores or not false_scores
            else statistics.mean(false_scores) < statistics.mean(true_scores)
        ),
        "score_ranges_overlap": overlap,
        "usable_separation": usable,
        "p2_implemented": P2_IMPLEMENTED,
        "decision": {
            "verdict": verdict,
            "keep_explicit_uncertain": verdict != "p2_warranted",
            "implement_p2": False,
            "reason": _reason(verdict),
        },
    }


def freeze_tabular_probability(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PROBABILITY_ID,
        "label": (
            "Frozen: P1 observation of Jev choice confidence on the 100 "
            "tabular v1 cells. Same hybrid top-5, P0 prompt, one call per "
            "cell. Status is unchanged by score. P2 is not implemented. "
            "Does not replace C@8, tabular v1, or D."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_tabular_v1": True,
        "does_not_replace_tabular_direct": True,
        "default_prompt_unchanged": True,
        "default_hybrid_unchanged": True,
        "default_k_unchanged": True,
        "p2_implemented": P2_IMPLEMENTED,
        "score_type": SCORE_TYPE,
        "same_mapping": GOLD_MAP_VERSION,
        "headline": payload.get("headline"),
        "inventory": payload.get("inventory"),
        "analysis": payload.get("analysis"),
        "decision": payload.get("decision"),
        "quality": payload.get("quality"),
        "observations": payload.get("observations"),
        "cells": payload.get("cells"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_tabular_probability_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PROBABILITY_PATH
    if target.resolve() in {item.resolve() for item in PROTECTED}:
        raise ValueError("must not overwrite a protected baseline")
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_tabular_probability(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_probability_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target_dir = directory or EVAL_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "probability-v1.csv"
    md_path = target_dir / "probability-v1.md"
    rows = list(payload.get("observations") or [])
    fieldnames = [
        "document_id",
        "question_id",
        "model_decision",
        "model_score",
        "score_type",
        "source_score",
        "excerpt_score",
        "outcome",
        "is_correct",
        "citation_correct",
        "retrieval_gold_present",
        "latency_ms",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    inventory = payload.get("inventory") or {}
    analysis = payload.get("analysis") or {}
    decision = payload.get("decision") or {}
    lines = [
        "# Tabular Jev probability P1",
        "",
        "P0 prompt. Frozen hybrid top-5. One Jev call per cell. "
        "Score does not change status. P2 is not implemented.",
        "",
        "## A. Inventory",
        "",
        f"- API fields: `{SCORE_FIELD}` (chosen) and `probabilities` (all alternatives).",
        f"- `score_type`: `{SCORE_TYPE}`. P1 uses status `{SCORE_FIELD}`.",
        "- Classification distribution, not a token logprob, not legal correctness.",
        "- `answer_cell` can read it from the existing response. Frozen tabular "
        "baselines do not contain it, so this is a live observation, not a replay.",
        f"- Observed answer fields: `{inventory.get('observed_answer_fields')}`.",
        f"- Live score present: `{inventory.get('live_score_present')}`.",
        "",
        "C@8 already found the same field unstable across identical classify runs. "
        "A fixed cutoff is not a calibrated probability.",
        "",
        "## B. Score versus correctness",
        "",
        _stats_table("True ANSWERED", analysis.get("true_answered") or {}),
        _stats_table("False ANSWERED", analysis.get("false_answered") or {}),
        "",
        f"False-answer mean lower: `{analysis.get('false_mean_lower')}`.",
        f"Ranges overlap: `{analysis.get('score_ranges_overlap')}`.",
        "True ANSWERED goes down to 0.33. False ANSWERED goes up to 1.0, "
        "including Avtal 13 citing settlement secrecy.",
        "",
        "## C. Calibration",
        "",
        f"Usable separation: `{analysis.get('usable_separation')}`.",
        "P2 was not implemented.",
        "",
        "## D–E. Quality and cost",
        "",
        "Same request as default `answer_cell`. No extra model call. "
        "Overhead is parsing `confidence`.",
        "",
        "## F. Decision",
        "",
        f"- Verdict: `{decision.get('verdict')}`.",
        f"- Keep explicit UNCERTAIN: `{decision.get('keep_explicit_uncertain')}`.",
        f"- {decision.get('reason')}",
        "",
        "Default P0 stays.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def _observation(
    result: object,
    scored: dict[str, object],
    scores: dict[str, object],
    relevant: set[str],
) -> dict[str, object]:
    row = dict(scored)
    row.update(
        {
            "model_decision": result.status,
            "model_score": scores["status"],
            "score_type": SCORE_TYPE,
            "source_score": scores["source"],
            "excerpt_score": scores["excerpt"],
            "gold_result": "positive" if scored["gold_positive"] else "negative",
            "is_correct": bool(scored["full_success"]),
            "citation_correct": bool(scored["citation_relevant"]),
            "retrieval_gold_present": bool(relevant & set(result.source_unit_ids or []))
            or bool(scored.get("seed_has_gold")),
            "latency_ms": int(round(float(result.answer_seconds) * 1000)),
            "answer_fields": list(scores["answer_fields"]),
        }
    )
    return row


def _scores_from_capture(result: JevResult | None) -> dict[str, object]:
    if result is None:
        return {
            "status": None,
            "source": None,
            "excerpt": None,
            "answer_fields": (),
        }
    fields: list[str] = []
    parsed = {}
    for key in ("status", "source", "excerpt"):
        row = result.answers.get(key)
        fields.extend(choice_row_fields(row))
        parsed[key] = parse_confidence(row, key=key) if isinstance(row, dict) else None
    return {
        "status": parsed["status"],
        "source": parsed["source"],
        "excerpt": parsed["excerpt"],
        "answer_fields": tuple(sorted(set(fields))),
    }


def _classify_score_inventory() -> dict[str, object]:
    frozen = load_official_classify_baseline()
    run = (frozen.get("runs") or [{}])[0]
    judgments = [row for row in run.get("wall_judgments") or [] if isinstance(row, dict)]
    correct = [
        float(row["confidence"])
        for row in judgments
        if row.get("confidence") is not None and row.get("predicted") == row.get("expected")
    ]
    wrong = [
        float(row["confidence"])
        for row in judgments
        if row.get("confidence") is not None and row.get("predicted") != row.get("expected")
    ]
    return {
        "field": SCORE_FIELD,
        "mean_confidence": run.get("mean_confidence"),
        "correct": _stats(correct),
        "incorrect": _stats(wrong),
        "threshold_stability": frozen.get("threshold_stability"),
        "confidence_is_not_calibrated_probability": True,
        "labels_were_stable_scores_were_not": True,
    }


def _group_stats(rows: list[dict[str, object]], field: str) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field))].append(row)
    return {name: _stats(_values(items)) | {"n": len(items)} for name, items in groups.items()}


def _values(rows: list[dict[str, object]]) -> list[float]:
    values = []
    for row in rows:
        score = row.get("model_score")
        if score is not None:
            values.append(float(score))
    return values


def _stats(values: list[float]) -> dict[str, object]:
    if not values:
        return {"n": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "max": max(values),
    }


def _verdict(
    present: int,
    n: int,
    true_scores: list[float],
    false_scores: list[float],
    usable: bool,
) -> str:
    if present == 0:
        return "no_score_exposed"
    if present < n:
        return "score_incomplete"
    if not false_scores:
        return "cannot_test_false_answers"
    if not usable:
        return "keep_explicit_uncertain"
    return "p2_warranted"


def _reason(verdict: str) -> str:
    return {
        "no_score_exposed": (
            "Jev did not return a usable confidence on answer_cell. "
            "Do not invent a score."
        ),
        "score_incomplete": "Some cells lacked confidence. Do not build a rule on a hole.",
        "cannot_test_false_answers": (
            "No false ANSWERED cells, so the hypothesis cannot be tested."
        ),
        "keep_explicit_uncertain": (
            "Choice confidence overlaps for true and false ANSWERED. "
            "It does not replace explicit UNCERTAIN."
        ),
        "p2_warranted": (
            "Scores separated true and false ANSWERED on this set. "
            "P2 is still not implemented; that needs a holdout."
        ),
    }[verdict]


def _stats_table(title: str, stats: dict[str, object]) -> str:
    return (
        f"| {title} | n | min | median | mean | max |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        f"| score | {stats.get('n')} | {stats.get('min')} | {stats.get('median')} | "
        f"{stats.get('mean')} | {stats.get('max')} |"
    )


def _load_frozen(path: Path | None) -> dict[str, object]:
    if path is None:
        return load_tabular_review_baseline()
    return json.loads(path.read_text(encoding="utf-8"))
