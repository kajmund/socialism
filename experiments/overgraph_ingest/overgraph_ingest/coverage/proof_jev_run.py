"""Jev proof evaluator on frozen morph cases. Does not change C@8 or v3."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from overgraph_ingest.coverage.proof_link import LINKED_RELATION
from overgraph_ingest.coverage.proof_morph import CASES, EVEN_CASE, GROUPS, INTE_CASE, run_proof_morph
from overgraph_ingest.jev.client import HttpJevClient, JevClient, JevError, JevUsage
from overgraph_ingest.jev.proof_eval import (
    PROOF_QUESTION,
    evidence_passage,
    evidence_resolved,
    evidence_units,
    parse_proof_choice,
    proof_choice_question,
)

PROOF_JEV_BASELINE_ID = "phase2-proof-jev-morph-v1"
PROOF_JEV_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_JEV_BASELINE_ID}.json"
)
CONTRADICTED_IDS = {
    "negation_gäller_även",
    "negation_gäller_också",
    "negation_gäller_utan_inte",
    "negation_tillampas_aven",
    "negation_inget_undantag",
    "negation_endast_uppsat",
    "negation_gäller_inte_utom_sekretess",
    "negation_dock_vid",
}
HARD_FALSE_COMPLETE_IDS = (
    "negation_split_same_unit",
    "negation_gäller_inte_utom_sekretess",
)


def expected_proof_label(case: dict[str, object], *, phase: str) -> str:
    if phase == "after":
        after = case.get("expected_after")
        if after == LINKED_RELATION:
            return "SUPPORTED"
        return "INSUFFICIENT"
    if case["expected"] == LINKED_RELATION:
        return "SUPPORTED"
    if case["id"] in CONTRADICTED_IDS:
        return "CONTRADICTED"
    return "INSUFFICIENT"


def pack_evidence(case: dict[str, object], *, phase: str) -> dict[str, object]:
    texts = [str(item) for item in case["texts"]]
    nav = case.get("navigate")
    if phase == "after" and nav:
        source, target = int(nav[0]), int(nav[1])
        return evidence_resolved(texts[source], texts[target])
    if nav:
        return evidence_passage(texts[int(nav[0])])
    if len(texts) == 1:
        return evidence_passage(texts[0])
    return evidence_units(texts)


def run_proof_jev(
    *,
    client: JevClient,
    model: str = "jev-1.13.0",
    timeout_seconds: float = 8.0,
    concurrency: int = 8,
) -> dict[str, object]:
    jobs = _jobs()
    started = time.perf_counter()
    rows = _run_jobs(
        jobs,
        client=client,
        model=model,
        timeout_seconds=timeout_seconds,
        concurrency=concurrency,
    )
    wall = time.perf_counter() - started
    by_id = {row["id"]: row for row in rows if row["phase"] == "before"}
    after_by_id = {row["id"]: row for row in rows if row["phase"] == "after"}
    morph = run_proof_morph()
    false_complete = [
        row["id"]
        for row in rows
        if row["predicted"] == "SUPPORTED" and row["expected"] != "SUPPORTED"
    ]
    hard_false = [case_id for case_id in HARD_FALSE_COMPLETE_IDS if case_id in false_complete]
    synonym = [row for row in rows if row["group"] == "synonym" and row["phase"] == "before"]
    return {
        "operation": "coverage",
        "experiment": "proof_jev_morph_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "classify_unchanged": True,
        "one_judgment_per_prompt": True,
        "not_an_independent_blind_test": True,
        "proof_question": PROOF_QUESTION,
        "jev_model": model,
        "concurrency": concurrency,
        "case_count": len(CASES),
        "judgment_count": len(rows),
        "passed": sum(1 for row in rows if row["pass"]),
        "false_complete": false_complete,
        "false_complete_count": len(false_complete),
        "hard_false_complete": hard_false,
        "zero_false_complete": not false_complete,
        "synonym_recall": _rate(synonym, "SUPPORTED"),
        "insufficient_when_unlinked": _insufficient_rate(rows),
        "even_versus_inte": {
            "even": by_id[EVEN_CASE]["predicted"],
            "inte": by_id[INTE_CASE]["predicted"],
            "distinguishes": by_id[EVEN_CASE]["predicted"] != by_id[INTE_CASE]["predicted"],
        },
        "groups": {
            name: _group_score(rows, name)
            for name in GROUPS
        },
        "versus_deterministic": {
            "deterministic_passed": morph["passed"],
            "deterministic_synonym_recall": morph["synonym_recall"],
            "deterministic_false_complete_count": morph["false_complete_count"],
            "jev_passed": sum(1 for row in rows if row["pass"]),
            "jev_synonym_recall": _rate(synonym, "SUPPORTED"),
            "jev_false_complete_count": len(false_complete),
        },
        "latency_ms_mean": _mean([row["latency_ms"] for row in rows]),
        "total_tokens": sum(int(row["total_tokens"] or 0) for row in rows),
        "wall_seconds": wall,
        "judgments": rows,
        "after_navigation": list(after_by_id.values()),
    }


def freeze_proof_jev_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PROOF_JEV_BASELINE_ID,
        "label": (
            "Frozen: Jev proof evaluation on the same 40 morph cases. "
            "Not C@8 and not an independent blind test."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "classify_unchanged": True,
        "not_an_independent_blind_test": True,
        "zero_false_complete": payload.get("zero_false_complete"),
        "headline": {
            "passed": payload.get("passed"),
            "judgment_count": payload.get("judgment_count"),
            "false_complete_count": payload.get("false_complete_count"),
            "hard_false_complete": payload.get("hard_false_complete"),
            "synonym_recall": payload.get("synonym_recall"),
            "even_versus_inte": payload.get("even_versus_inte"),
            "versus_deterministic": payload.get("versus_deterministic"),
            "latency_ms_mean": payload.get("latency_ms_mean"),
            "total_tokens": payload.get("total_tokens"),
            "wall_seconds": payload.get("wall_seconds"),
        },
        "groups": payload.get("groups"),
    }


def write_proof_jev_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PROOF_JEV_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_jev_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_jev_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or PROOF_JEV_BASELINE_PATH).read_text(encoding="utf-8"))


def _jobs() -> list[dict[str, object]]:
    jobs = []
    for case in CASES:
        jobs.append({**case, "phase": "before", "job_id": str(case["id"])})
        if case.get("navigate"):
            jobs.append({**case, "phase": "after", "job_id": f"{case['id']}::after"})
    return jobs


def _run_jobs(
    jobs: list[dict[str, object]],
    *,
    client: JevClient,
    model: str,
    timeout_seconds: float,
    concurrency: int,
) -> list[dict[str, object]]:
    if concurrency == 1 or len(jobs) <= 1:
        return [
            _ask_one(job, client=client, model=model, timeout_seconds=timeout_seconds, call_index=index)
            for index, job in enumerate(jobs)
        ]
    by_index: dict[int, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                _ask_one,
                job,
                client=client,
                model=model,
                timeout_seconds=timeout_seconds,
                call_index=index,
            ): index
            for index, job in enumerate(jobs)
        }
        for future, index in futures.items():
            by_index[index] = future.result()
    return [by_index[index] for index in range(len(jobs))]


def _ask_one(
    job: dict[str, object],
    *,
    client: JevClient,
    model: str,
    timeout_seconds: float,
    call_index: int,
) -> dict[str, object]:
    phase = str(job["phase"])
    expected = expected_proof_label(job, phase=phase)
    evidence = pack_evidence(job, phase=phase)
    key = str(job["job_id"])
    state = {
        "task": PROOF_QUESTION,
        "judge": "marked_evidence_only",
        "does_not_replace_classify": True,
        "evidence": evidence,
    }
    predicted = "INSUFFICIENT"
    confidence = None
    latency_ms = 0.0
    usage = JevUsage()
    error = None
    try:
        result = client.ask(
            state=state,
            questions={key: proof_choice_question()},
            model=model,
            timeout_seconds=timeout_seconds,
        )
        predicted, confidence = parse_proof_choice(result.answers, key)
        latency_ms = result.latency_ms
        usage = result.usage
    except JevError as exc:
        error = f"{exc.category}: {exc}"
    return {
        "id": job["id"],
        "job_id": key,
        "phase": phase,
        "group": job["group"],
        "expected": expected,
        "predicted": predicted,
        "pass": predicted == expected,
        "false_complete": predicted == "SUPPORTED" and expected != "SUPPORTED",
        "confidence": confidence,
        "latency_ms": latency_ms,
        "total_tokens": usage.total_tokens,
        "call_index": call_index,
        "error": error,
        "evidence_kind": evidence["kind"],
    }


def _rate(rows: list[dict[str, object]], label: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row["predicted"] == label) / len(rows)


def _insufficient_rate(rows: list[dict[str, object]]) -> float:
    wanted = [row for row in rows if row["expected"] == "INSUFFICIENT"]
    if not wanted:
        return 0.0
    return sum(1 for row in wanted if row["predicted"] == "INSUFFICIENT") / len(wanted)


def _group_score(rows: list[dict[str, object]], name: str) -> dict[str, object]:
    group = [row for row in rows if row["group"] == name]
    return {
        "count": len(group),
        "passed": sum(1 for row in group if row["pass"]),
        "false_complete": [row["id"] for row in group if row["false_complete"]],
    }


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
