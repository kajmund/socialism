"""Regression requirements from observed blind traces. Not a proof engine."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.retrieval.conclusions import load_blind_trace_run_baseline

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_BASELINE_ID = "phase2-proof-requirements-v1"
REQUIREMENTS_BASELINE_PATH = ROOT / "baselines" / f"{REQUIREMENTS_BASELINE_ID}.json"

PREVAILING_TERMS = "prevailing_terms"
FORMULATION_PRESENCE = "formulation_presence"

AMENDMENT_MUST_NOT_BE_IGNORED = "amendment_of_cited_provision"
MISSING_LINK_NEEDS_RIGHT_MATERIAL = "missing_link_resolved_by_cited_material"
EXISTING_LINK_WITHOUT_OBLIGATORY_HOP = "existing_link_usable_without_hop"

REJECTED_FIXES = (
    "no_always_wins_over_yes",
    "first_model_answer_wins",
    "last_model_answer_wins",
    "any_successful_hop_resolves_reference",
    "join_nearby_units",
    "force_uncertain_to_no",
)

EVIDENCE_FOUND_MUST_ANSWER = (
    "which_text_supports_the_conclusion",
    "how_the_parts_are_linked",
    "whether_examined_text_amends_the_cited_provision",
)


def accounting(frozen: dict[str, object] | None = None) -> dict[str, object]:
    headline = (frozen or load_blind_trace_run_baseline())["headline"]
    yes = int(headline["documents_found"])
    no = int(headline["observed_false_complete_count"])
    uncertain = int(headline["complete_uncertain_count"])
    return {
        "gold_yes": yes,
        "gold_no": no,
        "gold_uncertain": uncertain,
        "total_evidence_found": yes + no + uncertain,
        "gold_yes_is_not_verified_proof": True,
        "uncertain_is_not_false_complete": True,
        "uncertain_is_not_verified_proof": True,
        "all_jev_yes_after_hop": headline["all_found_reasons_jev_yes_after_hop"],
    }


def case_by_id(document_id: str, frozen: dict[str, object] | None = None) -> dict[str, object]:
    payload = frozen or load_blind_trace_run_baseline()
    for group in ("false_complete", "complete_uncertain", "true_complete_missed_by_detector"):
        for row in payload.get(group) or []:
            if row.get("document_id") == document_id:
                return dict(row)
    raise KeyError(document_id)


def current_completion_satisfies(requirement: str, row: dict[str, object]) -> bool:
    """Hop-always EVIDENCE_FOUND does not satisfy the observed requirements."""
    del requirement, row
    return False


def hop_resolves_cited_material(row: dict[str, object]) -> bool:
    yes = str(row.get("jev_yes_text") or "")
    hop = str(row.get("hop_text") or "")
    if "avsnitt 4" in yes.lower():
        return "avsnitt 4" in hop.lower() or "skyldighet" in hop.lower()
    return False


def existing_link_in_yes_unit(row: dict[str, object]) -> bool:
    text = str(row.get("jev_yes_text") or "")
    return any(
        marker in text
        for marker in (
            "Detsamma gäller",
            "Samma sak gäller",
            "gäller inte i följande fall",
            "Konfidentiell Information",
            "Förtrolig Information",
        )
    )


def run_proof_requirements() -> dict[str, object]:
    frozen = load_blind_trace_run_baseline()
    counts = accounting(frozen)
    amendment = [case_by_id(path, frozen) for path in ("avtal_119.docx", "avtal_200.docx")]
    missing = case_by_id("avtal_103.docx", frozen)
    existing = [case_by_id(path, frozen) for path in ("avtal_106.docx", "avtal_113.docx", "avtal_140.docx")]
    anaphor_hop = case_by_id("avtal_107.docx", frozen)
    uncertain = [case_by_id(path, frozen) for path in ("avtal_138.docx", "avtal_142.docx", "avtal_173.docx")]
    return {
        "operation": "coverage",
        "experiment": "proof_requirements_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "no_new_proof_engine": True,
        "no_link_re_change": True,
        "applied_to_v3": False,
        "answer_contract": PREVAILING_TERMS,
        "answer_contract_is_not": FORMULATION_PRESENCE,
        "evidence_proof_shape_still_starting_point": True,
        "active_completion_does_not_require_proof": True,
        "accounting": counts,
        "requirements": {
            AMENDMENT_MUST_NOT_BE_IGNORED: {
                "documents": [row["document_id"] for row in amendment],
                "current_completion_satisfies": all(
                    current_completion_satisfies(AMENDMENT_MUST_NOT_BE_IGNORED, row)
                    for row in amendment
                ),
                "local_yes_may_be_reasonable": True,
                "document_decision_is_wrong": True,
            },
            MISSING_LINK_NEEDS_RIGHT_MATERIAL: {
                "documents": [missing["document_id"]],
                "hop_resolves_cited_material": hop_resolves_cited_material(missing),
                "current_completion_satisfies": current_completion_satisfies(
                    MISSING_LINK_NEEDS_RIGHT_MATERIAL, missing
                ),
            },
            EXISTING_LINK_WITHOUT_OBLIGATORY_HOP: {
                "documents": [row["document_id"] for row in existing],
                "existing_link_in_yes_unit": all(existing_link_in_yes_unit(row) for row in existing),
                "hop_was_required_by_controller": all(
                    row.get("why_evidence_found") == "jev_yes_after_hop" for row in existing
                ),
                "current_completion_satisfies": all(
                    current_completion_satisfies(EXISTING_LINK_WITHOUT_OBLIGATORY_HOP, row)
                    for row in existing
                ),
            },
        },
        "anaphor_hop_is_right_material_but_unchecked": {
            "document_id": anaphor_hop["document_id"],
            "hop_text": anaphor_hop.get("hop_text"),
            "controller_checks_the_link": False,
        },
        "uncertain_stays_unresolved": {
            "documents": [row["document_id"] for row in uncertain],
            "must_not_force_no": True,
            "must_not_count_as_verified": True,
        },
        "rejected_fixes": list(REJECTED_FIXES),
        "evidence_found_must_answer": list(EVIDENCE_FOUND_MUST_ANSWER),
        "unmapped_gold_quote": {
            "relative_path": "avtal_160.docx",
            "span": (
                "Alternativ A ☒ Begränsningen i § 6 första stycket gäller inte vid brott mot § 5."
            ),
            "reason": "exact_contains_miss_extra_space_after_ballot",
            "is_ranking_miss": False,
            "document_is_in_graph": True,
        },
    }


def freeze_proof_requirements_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": REQUIREMENTS_BASELINE_ID,
        "label": (
            "Frozen: three regression requirements from observed blind traces. "
            "Not a proof engine. Not applied to v3."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_proof_engine": True,
        "applied_to_v3": False,
        "headline": {
            "answer_contract": payload.get("answer_contract"),
            "accounting": payload.get("accounting"),
            "requirements_current_completion_satisfies": {
                name: row.get("current_completion_satisfies")
                for name, row in (payload.get("requirements") or {}).items()
            },
            "rejected_fixes": payload.get("rejected_fixes"),
            "unmapped_gold_quote": payload.get("unmapped_gold_quote"),
        },
        "requirements": payload.get("requirements"),
        "anaphor_hop_is_right_material_but_unchecked": payload.get(
            "anaphor_hop_is_right_material_but_unchecked"
        ),
        "uncertain_stays_unresolved": payload.get("uncertain_stays_unresolved"),
        "evidence_found_must_answer": payload.get("evidence_found_must_answer"),
    }


def write_proof_requirements_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or REQUIREMENTS_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_requirements_baseline(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target
