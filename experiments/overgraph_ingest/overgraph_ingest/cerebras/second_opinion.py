"""Replay Jev C@8 versus GPT-OSS on overlapping top-50 keys. No router. No new calls."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.cerebras.evaluate import relevant_keys
from overgraph_ingest.cerebras.output import DEFAULT_FROZEN
from overgraph_ingest.cerebras.prompt import MATCH, NO_MATCH, TASK, UNCERTAIN
from overgraph_ingest.cerebras.run import DEFAULT_DB, DEFAULT_GOLD_DIR, _mean, _sum
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.coverage.run import _golds
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.baseline import load_baseline_judgments
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[2]
SECOND_OPINION_ID = "phase2-cerebras-second-opinion-v1"
SECOND_OPINION_PATH = ROOT / "baselines" / f"{SECOND_OPINION_ID}.json"
DEFAULT_CEREBRAS = ROOT / "data" / "cerebras-output-v1.json"
JEV_YES = "YES"
JEV_NO = "NO"
POSITIVE = "POSITIVE"
NEGATIVE = "NEGATIVE"
ABSTAIN = "ABSTAIN"
JEV_SOURCES = {
    "auto-renewal": ROOT / "baselines" / "phase2-jev-classify-c8.json",
    "notice-period": ROOT / "data" / "jev-notice-period-C8.json",
    "liability-cap": ROOT / "data" / "jev-liability-cap-C8.json",
    "confidentiality": ROOT / "data" / "jev-confidentiality-C8.json",
    "liability-secrecy-carveout": ROOT / "data" / "jev-liability-secrecy-carveout-C8.json",
}


def polarity(label: str) -> str:
    if label in {JEV_YES, MATCH}:
        return POSITIVE
    if label in {JEV_NO, NO_MATCH}:
        return NEGATIVE
    if label == UNCERTAIN:
        return ABSTAIN
    raise ValueError(f"unsupported label: {label}")


def role(*, label: str, relevant: bool) -> str:
    side = polarity(label)
    if side == ABSTAIN:
        return "uncertain"
    if side == POSITIVE:
        return "true_positive" if relevant else "false_positive"
    return "false_negative" if relevant else "true_negative"


def pair_effect(jev_role: str, cerebras_role: str) -> str:
    jev_error = jev_role in {"false_positive", "false_negative"}
    cerebras_error = cerebras_role in {"false_positive", "false_negative"}
    jev_correct = jev_role in {"true_positive", "true_negative"}
    cerebras_correct = cerebras_role in {"true_positive", "true_negative"}
    if jev_error and cerebras_correct:
        return "corrected"
    if jev_correct and cerebras_error:
        return "worsened"
    if jev_error and cerebras_error:
        return "same_error" if jev_role == cerebras_role else "shared_error"
    if jev_role == "uncertain" and cerebras_correct:
        return "uncertain_resolved_correct"
    if jev_role == "uncertain" and cerebras_error:
        return "uncertain_resolved_wrong"
    if jev_role == "uncertain" and cerebras_role == "uncertain":
        return "both_uncertain"
    if cerebras_role == "uncertain" and jev_correct:
        return "cerebras_abstained_jev_correct"
    if cerebras_role == "uncertain" and jev_error:
        return "cerebras_abstained_jev_error"
    if jev_correct and cerebras_correct:
        return "both_correct"
    raise ValueError(f"unhandled pair: {jev_role} / {cerebras_role}")


def compare_pairs(
    *,
    jev: dict[str, str],
    cerebras: dict[str, str],
    corpus_keys: set[str],
) -> dict[str, object]:
    overlap = sorted(set(jev) & set(cerebras))
    rows: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for key in overlap:
        relevant = key in corpus_keys
        jev_role = role(label=jev[key], relevant=relevant)
        cerebras_role = role(label=cerebras[key], relevant=relevant)
        effect = pair_effect(jev_role, cerebras_role)
        counts[effect] = counts.get(effect, 0) + 1
        rows.append(
            {
                "key": key,
                "relevant": relevant,
                "jev": jev[key],
                "cerebras": cerebras[key],
                "jev_role": jev_role,
                "cerebras_role": cerebras_role,
                "effect": effect,
            }
        )
    jev_errors = [row for row in rows if row["jev_role"] in {"false_positive", "false_negative"}]
    jev_correct = [row for row in rows if row["jev_role"] in {"true_positive", "true_negative"}]
    return {
        "overlap": len(overlap),
        "jev_only": sorted(set(jev) - set(cerebras)),
        "cerebras_only": sorted(set(cerebras) - set(jev)),
        "relevant_in_overlap": sum(1 for key in overlap if key in corpus_keys),
        "jev_errors": len(jev_errors),
        "jev_correct": len(jev_correct),
        "jev_uncertain": sum(1 for row in rows if row["jev_role"] == "uncertain"),
        "corrected": counts.get("corrected", 0),
        "worsened": counts.get("worsened", 0),
        "same_error": counts.get("same_error", 0),
        "shared_error": counts.get("shared_error", 0),
        "both_correct": counts.get("both_correct", 0),
        "uncertain_resolved_correct": counts.get("uncertain_resolved_correct", 0),
        "uncertain_resolved_wrong": counts.get("uncertain_resolved_wrong", 0),
        "both_uncertain": counts.get("both_uncertain", 0),
        "cerebras_abstained_jev_correct": counts.get("cerebras_abstained_jev_correct", 0),
        "cerebras_abstained_jev_error": counts.get("cerebras_abstained_jev_error", 0),
        "effects": counts,
        "pairs": rows,
        "jev_rescored": _rescored(jev, overlap, corpus_keys),
        "cerebras_rescored": _rescored(cerebras, overlap, corpus_keys),
        "uncertain_review": _uncertain_review(jev, cerebras, overlap, corpus_keys),
    }


def run_cerebras_second_opinion(
    *,
    db_path: Path | None = None,
    gold_dir: Path | None = None,
    dense_dimension: int = 3072,
    cerebras_path: Path | None = None,
    jev_paths: dict[str, Path] | None = None,
    jev_by_gold: dict[str, dict[str, str]] | None = None,
    cerebras_by_gold: dict[str, dict[str, str]] | None = None,
    corpus_keys_by_gold: dict[str, set[str]] | None = None,
) -> dict[str, object]:
    golds = _golds(None, gold_dir or DEFAULT_GOLD_DIR)
    if not golds:
        raise ValueError("no seen golds")
    if corpus_keys_by_gold is None:
        target = db_path or DEFAULT_DB
        dimension = resolve_dimension(target, dense_dimension)
        db = open_database(target, dimension)
        try:
            units = load_graph_context(GraphWriter(db, batch_size=500)).units
        finally:
            db.close()
        corpus_keys_by_gold = {gold.id: relevant_keys(units, gold) for gold in golds}
    if jev_by_gold is None:
        sources = jev_paths or JEV_SOURCES
        jev_by_gold = {
            gold.id: {
                str(row["key"]): str(row["predicted"])
                for row in load_baseline_judgments(sources[gold.id])
            }
            for gold in golds
        }
    if cerebras_by_gold is None:
        cerebras_by_gold = _load_cerebras_labels(cerebras_path or DEFAULT_CEREBRAS)
    frozen_keys = _load_frozen_keys(DEFAULT_FROZEN)
    rows: list[dict[str, object]] = []
    for gold in golds:
        compared = compare_pairs(
            jev=jev_by_gold[gold.id],
            cerebras=cerebras_by_gold[gold.id],
            corpus_keys=corpus_keys_by_gold[gold.id],
        )
        compared["gold_id"] = gold.id
        compared["query"] = gold.query
        compared["jev_candidates"] = len(jev_by_gold[gold.id])
        compared["cerebras_candidates"] = len(cerebras_by_gold[gold.id])
        compared["frozen_top50_overlap_with_jev"] = len(
            set(frozen_keys[gold.id]) & set(jev_by_gold[gold.id])
        )
        source = (jev_paths or JEV_SOURCES).get(gold.id)
        compared["original_jev_relevant"] = (
            None if source is None else _original_jev_relevant(source)
        )
        rows.append(compared)
    return {
        "operation": "second_opinion_replay",
        "experiment": "cerebras_second_opinion_v1",
        "task": TASK,
        "same_mapping": GOLD_MAP_VERSION,
        "no_new_jev": True,
        "no_new_cerebras": True,
        "no_router": True,
        "no_automatic_k_routing": True,
        "k200_not_started": True,
        "one_shot_k100_not_retried": True,
        "does_not_change_reasoning": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "applied_to_v3": False,
        "uncertain_is_not_match": True,
        "quality_reference": QUALITY_REFERENCE,
        "golds": rows,
        "summary": {
            "golds": len(rows),
            "total_overlap": _sum(rows, "overlap"),
            "total_jev_only": sum(len(row["jev_only"]) for row in rows),
            "total_cerebras_only": sum(len(row["cerebras_only"]) for row in rows),
            "total_jev_errors": _sum(rows, "jev_errors"),
            "total_jev_correct": _sum(rows, "jev_correct"),
            "total_corrected": _sum(rows, "corrected"),
            "total_worsened": _sum(rows, "worsened"),
            "total_same_error": _sum(rows, "same_error"),
            "total_shared_error": _sum(rows, "shared_error"),
            "total_both_correct": _sum(rows, "both_correct"),
            "total_jev_uncertain": _sum(rows, "jev_uncertain"),
            "total_uncertain_resolved_correct": _sum(rows, "uncertain_resolved_correct"),
            "total_uncertain_resolved_wrong": _sum(rows, "uncertain_resolved_wrong"),
            "mean_jev_precision": _mean(
                [row["jev_rescored"] for row in rows], "precision"
            ),
            "mean_cerebras_precision": _mean(
                [row["cerebras_rescored"] for row in rows], "precision"
            ),
            "mean_jev_recall": _mean([row["jev_rescored"] for row in rows], "recall"),
            "mean_cerebras_recall": _mean(
                [row["cerebras_rescored"] for row in rows], "recall"
            ),
            "uncertain_review_precision": _mean(
                [row["uncertain_review"] for row in rows], "precision"
            ),
            "uncertain_review_recall": _mean(
                [row["uncertain_review"] for row in rows], "recall"
            ),
        },
    }


def freeze_cerebras_second_opinion(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_cerebras_second_opinion()
    return {
        "id": SECOND_OPINION_ID,
        "label": (
            "Frozen: replay of Jev C@8 labels versus GPT-OSS output v1 on "
            "overlapping hybrid top-50 keys. Same gold-map v2. No new model "
            "calls and no router. Lists are not identical; only the "
            "intersection is compared. Does not replace C@8 or output v1. "
            "k=200 is not started. 24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_replace_cerebras_output": True,
        "no_new_jev": True,
        "no_new_cerebras": True,
        "no_router": True,
        "k200_not_started": True,
        "applied_to_v3": False,
        "same_mapping": GOLD_MAP_VERSION,
        "task": TASK,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "summary": body.get("summary"),
            "golds": [
                {
                    "gold_id": row.get("gold_id"),
                    "overlap": row.get("overlap"),
                    "jev_only": len(row.get("jev_only") or []),
                    "cerebras_only": len(row.get("cerebras_only") or []),
                    "relevant_in_overlap": row.get("relevant_in_overlap"),
                    "original_jev_relevant": row.get("original_jev_relevant"),
                    "jev_errors": row.get("jev_errors"),
                    "corrected": row.get("corrected"),
                    "worsened": row.get("worsened"),
                    "same_error": row.get("same_error"),
                    "shared_error": row.get("shared_error"),
                    "jev_uncertain": row.get("jev_uncertain"),
                    "uncertain_resolved_correct": row.get("uncertain_resolved_correct"),
                    "uncertain_resolved_wrong": row.get("uncertain_resolved_wrong"),
                    "jev_rescored": row.get("jev_rescored"),
                    "cerebras_rescored": row.get("cerebras_rescored"),
                    "uncertain_review": {
                        key: (row.get("uncertain_review") or {}).get(key)
                        for key in (
                            "reviewed",
                            "precision",
                            "recall",
                            "resolved_correct",
                            "resolved_wrong",
                        )
                    },
                }
                for row in body.get("golds") or []
            ],
        },
    }


def write_cerebras_second_opinion(
    payload: dict[str, object] | None = None,
    path: Path | None = None,
) -> Path:
    target = path or SECOND_OPINION_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_cerebras_second_opinion()
    target.write_text(
        json.dumps(freeze_cerebras_second_opinion(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _rescored(
    labels: dict[str, str],
    keys: list[str],
    corpus_keys: set[str],
) -> dict[str, object]:
    relevant = [key for key in keys if key in corpus_keys]
    positive = [key for key in keys if polarity(labels[key]) == POSITIVE]
    true_pos = [key for key in positive if key in corpus_keys]
    return {
        "relevant": len(relevant),
        "positive": len(positive),
        "true_positive": len(true_pos),
        "precision": (len(true_pos) / len(positive)) if positive else 0.0,
        "recall": (len(true_pos) / len(relevant)) if relevant else 0.0,
    }


def _uncertain_review(
    jev: dict[str, str],
    cerebras: dict[str, str],
    keys: list[str],
    corpus_keys: set[str],
) -> dict[str, object]:
    merged = dict(jev)
    reviewed = 0
    resolved_correct = 0
    resolved_wrong = 0
    for key in keys:
        if polarity(jev[key]) != ABSTAIN:
            continue
        reviewed += 1
        merged[key] = cerebras[key]
        cerebras_role = role(label=cerebras[key], relevant=key in corpus_keys)
        if cerebras_role in {"true_positive", "true_negative"}:
            resolved_correct += 1
        elif cerebras_role in {"false_positive", "false_negative"}:
            resolved_wrong += 1
    scored = _rescored(merged, keys, corpus_keys)
    scored.update(
        {
            "reviewed": reviewed,
            "resolved_correct": resolved_correct,
            "resolved_wrong": resolved_wrong,
        }
    )
    return scored


def _load_cerebras_labels(path: Path) -> dict[str, dict[str, str]]:
    body = json.loads(path.read_text(encoding="utf-8"))
    loaded: dict[str, dict[str, str]] = {}
    for row in body.get("golds") or []:
        loaded[str(row["gold_id"])] = {
            str(item["key"]): str(item["label"])
            for item in row.get("judgments") or []
            if isinstance(item, dict)
        }
    return loaded


def _load_frozen_keys(path: Path) -> dict[str, list[str]]:
    body = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row["gold_id"]): [str(item["key"]) for item in row.get("judgments") or []]
        for row in body.get("golds") or []
    }


def _original_jev_relevant(path: Path) -> int | None:
    if not path.exists():
        return None
    rows = load_baseline_judgments(path)
    if not rows:
        return None
    return sum(1 for row in rows if row.get("expected") == JEV_YES)
