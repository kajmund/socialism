"""Isolated Jev predicate extraction. Does not change C@8, v3, or the evidence contract."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from overgraph_ingest.coverage.logic_run import AVTAL_60_UNIT
from overgraph_ingest.coverage.predicate_check import check_predicate
from overgraph_ingest.coverage.proof_jev_run import pack_evidence
from overgraph_ingest.coverage.proof_morph import CASES, GROUPS
from overgraph_ingest.jev.client import JevClient, JevError, JevUsage
from overgraph_ingest.jev.predicate import (
    PREDICATE_TASK,
    candidate_spans,
    parse_predicate,
    predicate_questions,
)

ROOT = Path(__file__).resolve().parents[2]
PREDICATE_BASELINE_ID = "phase2-proof-predicate-v1"
PREDICATE_BASELINE_PATH = ROOT / "baselines" / f"{PREDICATE_BASELINE_ID}.json"
CLAIM_OPERATOR = "does_not_apply"
INVERTED_ID = "negation_gäller_inte_utom_sekretess"
WRONG_CLAUSE_ID = "reference_punkt_8_wrong"
COOCCURRENCE_NONE = (
    "cooccurrence_split_units",
    "cooccurrence_abc",
    "cooccurrence_heading",
    "cooccurrence_three_keywords",
    "cooccurrence_avtal37",
    "cooccurrence_only_b_changed",
)
DOES_NOT_APPLY_IDS = {
    "synonym_seed",
    "synonym_ansvarstak_tystnadsplikt",
    "synonym_rojande_konfidentiell",
    "synonym_obegransat",
    "synonym_tystnadsplikt",
    "synonym_konfidentiell_gilt",
    "synonym_overtradelse",
    "synonym_undantas",
    "synonym_inte_tillamplig",
    "synonym_taket",
    "negation_gäller_inte_control",
    "reference_direct",
    "reference_inline_and_punkt",
    "cooccurrence_keep_link",
    "cooccurrence_move_heading",
    "cooccurrence_false_then_true",
    "avtal_60",
}
APPLIES_IDS = {
    "negation_gäller_även",
    "negation_gäller_också",
    "negation_gäller_utan_inte",
    "negation_tillampas_aven",
    "negation_inget_undantag",
    "negation_endast_uppsat",
    "negation_dock_vid",
}
AFTER_NONE_IDS = {
    "reference_punkt_4_infosec",
    "reference_punkt_8_secrecy",
    "reference_punkt_8_wrong",
}
AFTER_CLAIM_IDS = {
    "reference_abc_verify_c",
    "cooccurrence_abc_then_link",
}


def expected_operator(case: dict[str, object], *, phase: str) -> str:
    case_id = str(case["id"])
    if phase == "after":
        if case_id in AFTER_NONE_IDS:
            return "none"
        if case_id in AFTER_CLAIM_IDS:
            return CLAIM_OPERATOR
    if case_id in DOES_NOT_APPLY_IDS:
        return CLAIM_OPERATOR
    if case_id in APPLIES_IDS:
        return "applies"
    if case_id == INVERTED_ID:
        return "inverted"
    return "none"


def expected_object(operator: str) -> str:
    if operator == "none":
        return "none"
    return "secrecy_breach"


def source_text(evidence: dict[str, object]) -> str:
    kind = str(evidence.get("kind") or "passage")
    if kind == "resolved_reference":
        return f"{evidence['source_text']}\n{evidence['target_text']}"
    if kind == "labeled_units":
        return "\n".join(str(unit["text"]) for unit in list(evidence.get("units") or []))
    return str(evidence.get("text") or "")


def run_proof_predicate(
    *,
    client: JevClient,
    model: str = "jev-1.13.0",
    timeout_seconds: float = 8.0,
    concurrency: int = 8,
) -> dict[str, object]:
    jobs = _jobs()
    rows = _run_jobs(
        jobs,
        client=client,
        model=model,
        timeout_seconds=timeout_seconds,
        concurrency=concurrency,
    )
    before = [row for row in rows if row["phase"] == "before"]
    synonyms = [row for row in before if row["group"] == "synonym"]
    inverted = next(row for row in before if row["id"] == INVERTED_ID)
    avtal_60 = next(row for row in before if row["id"] == "avtal_60")
    wrong = next(row for row in rows if row["id"] == WRONG_CLAUSE_ID and row["phase"] == "after")
    matching = next(
        row for row in rows if row["id"] == "reference_punkt_8_secrecy" and row["phase"] == "after"
    )
    cooccurrence = [row for row in before if row["id"] in COOCCURRENCE_NONE]
    found = [row["id"] for row in rows if row["evidence_found"]]
    proposed = [row for row in rows if row["tier"] == "proposed"]
    return {
        "operation": "coverage",
        "experiment": "proof_predicate_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_change_evidence_contract": True,
        "classify_unchanged": True,
        "not_a_supported_classifier": True,
        "proposed_is_not_evidence_found": all(not row["evidence_found"] for row in proposed),
        "jev_model": model,
        "judgment_count": len(rows),
        "operator_matches": sum(1 for row in rows if row["operator_match"]),
        "paraphrase_operator_recall": _rate(synonyms, "operator_match"),
        "inverted_operator": inverted["operator"],
        "inverted_not_found": inverted["evidence_found"] is False,
        "avtal_60_span": avtal_60["excerpt"],
        "avtal_60_picks_carveout_sentence": "utom vid" in str(avtal_60["excerpt"]),
        "avtal_60_not_indirect_damage": "indirekt skada" not in str(avtal_60["excerpt"]),
        "avtal_60_found": avtal_60["evidence_found"],
        "cooccurrence_none": all(row["operator"] == "none" for row in cooccurrence),
        "wrong_clause_none": wrong["operator"] == "none",
        "wrong_clause_object": wrong["object"],
        "wrong_clause_uses_heading_11": "11." in str(wrong["excerpt"]),
        "matching_heading_after": {
            "operator": matching["operator"],
            "object": matching["object"],
            "tier": matching["tier"],
            "evidence_found": matching["evidence_found"],
        },
        "false_found": [row["id"] for row in rows if row["false_found"]],
        "zero_false_complete": not any(row["false_found"] for row in rows),
        "verified_count": sum(1 for row in rows if row["tier"] == "verified"),
        "proposed_count": len(proposed),
        "insufficient_count": sum(1 for row in rows if row["tier"] == "insufficient"),
        "evidence_found_ids": found,
        "groups": {name: _group(rows, name) for name in GROUPS},
        "judgments": rows,
    }


def freeze_proof_predicate_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PREDICATE_BASELINE_ID,
        "label": (
            "Frozen: Jev extracts a typed predicate; structure admits verified only. "
            "Proposed is not EVIDENCE_FOUND. Not applied to v3."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_change_evidence_contract": True,
        "not_a_supported_classifier": True,
        "zero_false_complete": payload.get("zero_false_complete"),
        "headline": {
            "judgment_count": payload.get("judgment_count"),
            "operator_matches": payload.get("operator_matches"),
            "paraphrase_operator_recall": payload.get("paraphrase_operator_recall"),
            "inverted_operator": payload.get("inverted_operator"),
            "inverted_not_found": payload.get("inverted_not_found"),
            "avtal_60_picks_carveout_sentence": payload.get("avtal_60_picks_carveout_sentence"),
            "avtal_60_not_indirect_damage": payload.get("avtal_60_not_indirect_damage"),
            "avtal_60_found": payload.get("avtal_60_found"),
            "cooccurrence_none": payload.get("cooccurrence_none"),
            "wrong_clause_none": payload.get("wrong_clause_none"),
            "wrong_clause_object": payload.get("wrong_clause_object"),
            "wrong_clause_uses_heading_11": payload.get("wrong_clause_uses_heading_11"),
            "matching_heading_after": payload.get("matching_heading_after"),
            "proposed_is_not_evidence_found": payload.get("proposed_is_not_evidence_found"),
            "zero_false_complete": payload.get("zero_false_complete"),
            "verified_count": payload.get("verified_count"),
            "proposed_count": payload.get("proposed_count"),
            "insufficient_count": payload.get("insufficient_count"),
            "false_found": payload.get("false_found"),
        },
        "groups": payload.get("groups"),
    }


def write_proof_predicate_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PREDICATE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_predicate_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_predicate_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or PREDICATE_BASELINE_PATH).read_text(encoding="utf-8"))


def _jobs() -> list[dict[str, object]]:
    jobs = []
    for case in CASES:
        jobs.append({**case, "phase": "before", "job_id": str(case["id"])})
        if case.get("navigate"):
            jobs.append({**case, "phase": "after", "job_id": f"{case['id']}::after"})
    jobs.append(
        {
            "id": "avtal_60",
            "group": "avtal_60",
            "property": "predication_scope",
            "texts": [AVTAL_60_UNIT],
            "expected": "linked_relation",
            "navigate": None,
            "expected_after": None,
            "phase": "before",
            "job_id": "avtal_60",
        }
    )
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
    evidence = (
        {"kind": "passage", "text": AVTAL_60_UNIT}
        if job["id"] == "avtal_60"
        else pack_evidence(job, phase=phase)
    )
    candidates = candidate_spans(evidence)
    blob = source_text(evidence)
    want_op = expected_operator(job, phase=phase)
    want_obj = expected_object(want_op)
    operator = "none"
    obj = "none"
    excerpt = ""
    unit_id = "none"
    start = -1
    end = -1
    checked = {"tier": "insufficient", "evidence_found": False, "reason": "no_predicate", "form": "undecided"}
    latency_ms = 0.0
    usage = JevUsage()
    error = None
    try:
        result = client.ask(
            state={
                "task": PREDICATE_TASK,
                "does_not_decide_supported": True,
                "case_id": job["job_id"],
                "evidence": evidence,
                "candidates": candidates,
            },
            questions=predicate_questions(candidates),
            model=model,
            timeout_seconds=timeout_seconds,
        )
        pred = parse_predicate(result.answers, candidates, blob)
        checked = check_predicate(pred)
        operator = pred.operator
        obj = pred.object
        excerpt = pred.excerpt
        unit_id = pred.unit_id
        start = pred.start
        end = pred.end
        latency_ms = result.latency_ms
        usage = result.usage
    except JevError as exc:
        error = f"{exc.category}: {exc}"
    found = bool(checked["evidence_found"])
    return {
        "id": job["id"],
        "job_id": job["job_id"],
        "phase": phase,
        "group": job["group"],
        "expected_operator": want_op,
        "expected_object": want_obj,
        "operator": operator,
        "object": obj,
        "excerpt": excerpt,
        "unit_id": unit_id,
        "start": start,
        "end": end,
        "tier": checked["tier"],
        "reason": checked["reason"],
        "form": checked["form"],
        "evidence_found": found,
        "operator_match": operator == want_op,
        "object_match": obj == want_obj,
        "false_found": found and want_op != CLAIM_OPERATOR,
        "latency_ms": latency_ms,
        "total_tokens": usage.total_tokens,
        "call_index": call_index,
        "error": error,
        "candidate_count": len(candidates),
    }


def _rate(rows: list[dict[str, object]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row[field]) / len(rows)


def _group(rows: list[dict[str, object]], name: str) -> dict[str, object]:
    group = [row for row in rows if row["group"] == name]
    return {
        "count": len(group),
        "operator_matches": sum(1 for row in group if row["operator_match"]),
        "false_found": [row["id"] for row in group if row["false_found"]],
        "proposed": sum(1 for row in group if row["tier"] == "proposed"),
        "verified": sum(1 for row in group if row["tier"] == "verified"),
    }
