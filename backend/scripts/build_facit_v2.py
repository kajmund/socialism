"""Build and validate versioned golden facit v2. Historical artifacts untouched."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.services.research.sufficiency_experiment.facit_qa import (
    FacitCase,
    FacitEvidence,
    FacitRelation,
    FacitReview,
    dump_facit,
    validate_facit,
)
from app.services.research.sufficiency_experiment.gap_cases import (
    candidate_miss_synonyms,
    notice_compatible_entities,
    notice_compatible_periods,
    synonym_compatible_entity,
    synonym_compatible_scope,
    synonym_contradiction_notice,
    synonym_contradiction_semester,
)
from app.services.research.sufficiency_experiment.golden import all_golden_cases

OUT = Path("tests/integration/baselines/golden-facit-v2.json")
QA = Path("tests/integration/baselines/facit-qa-v1.json")

SPECS = {
    "short_sufficient": ("valid", "supportive", "question is answered by the supporting passage"),
    "no_support": ("valid", "supportive", "no relevant support exists"),
    "tail_counterevidence": ("valid", "contradiction", "support and contradiction at the tail"),
    "late_evidence": ("valid", "contradiction", "contradiction only at evidence-48"),
    "large_567k": ("diagnostic", "contradiction", "large evidence, facit pair not isolated"),
    "multi_obligation": ("valid", "supportive", "multiple obligations, support incomplete"),
    "missing_source_type": ("valid", "supportive", "required source type is missing"),
    "unknown_requirements": ("valid", "supportive", "requirements unknown"),
    "duplicate_sources": ("valid", "supportive", "duplicate sources are not independent"),
    "later_wave_contradiction": ("valid", "contradiction", "contradiction in a later wave"),
    "adversarial_empty": ("valid", "supportive", "empty evidence"),
    "duplicate_contradiction": ("valid", "contradiction", "duplicate-looking contradiction"),
    "independent_contradiction": ("valid", "contradiction", "independent contradiction"),
    "compatible_periods": ("invalid", "compatible_scope", "evidence is off-topic for the 36 § plan question"),
    "compatible_entities": ("invalid", "compatible_entity", "evidence is off-topic for the 36 § plan question"),
    "unknown_counterpart": ("valid", "unresolved_unknown", "counterpart unknown"),
    "pair_over_budget": ("valid", "contradiction", "pair context over budget"),
    "tail_claim_contradiction": ("valid", "contradiction", "contradiction last among claims"),
    "candidate_miss_synonyms": ("valid", "contradiction", "synonym contradiction missed by lexical generation"),
    "synonym_contradiction_semester": ("valid", "contradiction", "semester contradiction, low overlap"),
    "synonym_contradiction_notice": ("valid", "contradiction", "notice contradiction, low overlap"),
    "synonym_compatible_scope": ("valid", "compatible_scope", "different periods are compatible"),
    "synonym_compatible_entity": ("valid", "compatible_entity", "different entities are compatible"),
    "notice_compatible_periods": ("valid", "compatible_scope", "on-topic notice periods are compatible"),
    "notice_compatible_entities": ("valid", "compatible_entity", "on-topic notice entities are compatible"),
}


def _case(case, status: str, relation: str, rationale: str) -> FacitCase:
    evidence = tuple(
        FacitEvidence(
            evidence_id=item.evidence_id,
            excerpt=item.excerpt,
            status=item.status,
            source_type=item.source_type,
            provenance=dict(item.provenance),
            expected_relevance=status != "invalid",
        )
        for item in case.evidence
    )
    evidence_ids = tuple(item.evidence_id for item in case.evidence[:2])
    return FacitCase(
        case_id=case.case_id,
        version="v2",
        status=status,  # type: ignore[arg-type]
        plan_question=case.plan.needs[0].question,
        expected_decision=case.expected,
        evidence=evidence,
        relations=(FacitRelation(evidence_ids=evidence_ids, relation=relation),) if evidence_ids else (),
        rationale=rationale,
        review=FacitReview(
            method="deterministic_keyword_overlap+agent_review",
            reviewed_by="agent",
            independent_review_required=case.case_id.startswith("notice_"),
            notes="independent review pending for on-topic replacements" if case.case_id.startswith("notice_") else "",
        ),
        invalidation_reason=(
            "evidence does not answer the plan question but facit expected sufficient"
            if status == "invalid"
            else ""
        ),
    )


def main() -> int:
    cases = {case.case_id: case for case in all_golden_cases()}
    cases.update(
        {
            case.case_id: case
            for case in (
                candidate_miss_synonyms(),
                synonym_contradiction_semester(),
                synonym_contradiction_notice(),
                synonym_compatible_scope(),
                synonym_compatible_entity(),
                notice_compatible_periods(),
                notice_compatible_entities(),
            )
        }
    )
    facit = tuple(
        _case(cases[case_id], *SPECS[case_id])
        for case_id in SPECS
        if case_id in cases
    )
    policy = "v2b" if "--policy-v2b" in sys.argv else "v2"
    qa_path = QA.with_name("facit-qa-v2b.json") if policy == "v2b" else QA
    validation = validate_facit(facit, policy=policy)
    dump_facit(facit, OUT, version="v2")
    qa_path.write_text(
        json.dumps(
            {
                "version": "v2b" if policy == "v2b" else "v2",
                "facit": str(OUT),
                "cases": len(facit),
                "valid": sum(case.status == "valid" for case in facit),
                "invalid": sum(case.status == "invalid" for case in facit),
                "diagnostic": sum(case.status == "diagnostic" for case in facit),
                "policy": policy,
            "errors": list(validation.errors),
                "warnings": list(validation.warnings),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"errors": validation.errors, "warnings": validation.warnings}, indent=2))
    print(f"wrote {OUT} and {qa_path}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
