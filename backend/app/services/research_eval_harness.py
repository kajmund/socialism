"""Deterministic, stage-specific evaluation of frozen research artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

STAGES = (
    "plan_coverage",
    "source_relevance",
    "source_reuse",
    "source_dedup",
    "domain_extraction",
    "citation_grounding",
    "claim_coverage",
    "assessment_completeness",
    "expert_context",
)


@dataclass(frozen=True)
class StageResult:
    passed: bool
    regressions: tuple[str, ...]


def evaluate_case(golden: dict[str, Any], artifacts: dict[str, Any]) -> dict[str, StageResult]:
    """Compare pipeline outputs to a pinned case without invoking retrieval or an LLM."""
    report: dict[str, StageResult] = {}

    def record(stage: str, errors: list[str]) -> None:
        report[stage] = StageResult(passed=not errors, regressions=tuple(errors))

    expected_needs = set(golden["plan_topics"])
    actual_needs = set(artifacts.get("plan_topics", []))
    record(
        "plan_coverage",
        [f"missing topic: {need}" for need in sorted(expected_needs - actual_needs)],
    )

    actual_sources = artifacts.get("sources", {})
    source_errors = []
    for source_id, expected in golden["source_decisions"].items():
        actual = actual_sources.get(source_id)
        if actual is None:
            source_errors.append(f"missing source decision: {source_id}")
        elif actual.get("selected") is not expected:
            source_errors.append(f"incorrect source decision: {source_id}")
    record("source_relevance", source_errors)

    reuse = artifacts.get("source_reuse", {})
    expected_reuse = golden.get("source_reuse", {})
    reuse_errors = []
    for source_id, expected in expected_reuse.items():
        metrics = reuse.get(source_id)
        fetches = metrics.get("document_fetches") if isinstance(metrics, dict) else None
        if type(fetches) is not int:
            reuse_errors.append(f"{source_id}: missing document_fetches")
        elif fetches > expected["max_document_fetches"]:
            reuse_errors.append(f"{source_id}: extra provider document fetch")
    record("source_reuse", reuse_errors)
    grouped = artifacts.get("source_groups", {})
    record(
        "source_dedup",
        [
            f"{source_id}: duplicate source group"
            for source_id, expected in expected_reuse.items()
            if grouped.get(source_id, {}).get("group_count") != expected["group_count"]
        ],
    )

    results = artifacts.get("domain_results", {})
    extraction_errors = []
    citation_errors = []
    for source_id, expected_fields in golden["domain_expectations"].items():
        result = results.get(source_id)
        if result is None:
            extraction_errors.append(f"missing domain result: {source_id}")
            citation_errors.append(f"missing domain result: {source_id}")
            continue
        for field, expected in expected_fields.items():
            if result.get("fields", {}).get(field) != expected:
                extraction_errors.append(f"{source_id}: {field}")
        raw_text = result.get("raw_text", "")
        uri = result.get("source_uri")
        citations = result.get("citations", [])
        if not citations:
            citation_errors.append(f"{source_id}: no citations")
        for index, citation in enumerate(citations):
            if (
                citation.get("source_uri") != uri
                or not citation.get("quote")
                or citation["quote"] not in raw_text
            ):
                citation_errors.append(f"{source_id}: ungrounded citation {index}")
    record("domain_extraction", extraction_errors)
    record("citation_grounding", citation_errors)

    claims = artifacts.get("claims", [])
    actual_claims = {
        (
            row.get("research_need_id"),
            row.get("predicate"),
            json.dumps(row.get("value"), sort_keys=True),
        )
        for row in claims
    }
    claim_errors = []
    for expected in golden["claims"]:
        key = (
            expected["research_need_id"],
            expected["predicate"],
            json.dumps(expected["value"], sort_keys=True),
        )
        if key not in actual_claims:
            claim_errors.append(
                f"missing claim: {expected['research_need_id']} / {expected['predicate']} / {expected['value']}"
            )
    for claim in claims:
        source_id = claim.get("source_id")
        source = results.get(source_id, {})
        citations = claim.get("citations", [])
        if not citations or any(
            citation.get("source_uri") != source.get("source_uri")
            or citation.get("quote") not in source.get("raw_text", "")
            for citation in citations
        ):
            claim_errors.append(f"ungrounded claim: {claim.get('id', claim.get('predicate'))}")
    record("claim_coverage", claim_errors)

    assessment = artifacts.get("assessment", {})
    assessment_errors = []
    for need_id, expected in golden["assessment"].items():
        if assessment.get("needs", {}).get(need_id) is not expected:
            assessment_errors.append(f"incorrect need assessment: {need_id}")
    if assessment.get("completeness") != golden["completeness"]:
        assessment_errors.append("incorrect global completeness")
    record("assessment_completeness", assessment_errors)

    expert = artifacts.get("expert_context", {})
    claim_ids = {row.get("id") for row in claims}
    used = set(expert.get("claim_ids", []))
    expert_errors = [
        f"missing expert claim: {value}"
        for value in golden["expert_claim_ids"]
        if value not in used
    ]
    expert_errors += [f"unknown expert claim: {value}" for value in sorted(used - claim_ids)]
    expert_text = str(expert.get("text") or "")
    expert_errors += [
        f"missing expert context: {marker}"
        for marker in golden.get("expert_context_markers", [])
        if marker not in expert_text
    ]
    record("expert_context", expert_errors)
    return report


def load_case(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    case = json.loads(path.read_text(encoding="utf-8"))
    return case["golden"], case["artifacts"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a frozen research case by stage")
    parser.add_argument("case", type=Path)
    parser.add_argument("--artifacts", type=Path, help="Optional pipeline output JSON")
    args = parser.parse_args()
    golden, included = load_case(args.case)
    artifacts = (
        json.loads(args.artifacts.read_text(encoding="utf-8")) if args.artifacts else included
    )
    report = evaluate_case(golden, artifacts)
    print(
        json.dumps({stage: asdict(report[stage]) for stage in STAGES}, ensure_ascii=False, indent=2)
    )
    return 0 if all(row.passed for row in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
