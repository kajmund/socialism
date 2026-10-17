from pathlib import Path

from overgraph_ingest.coverage.proof_contract import (
    COMPLETE_IN_UNIT,
    CURRENT_HOP,
    NEEDS_COMPLEMENTARY,
    UNRESOLVED_REFERENCE,
    current_status,
    evidence_in_text,
    proposed_status,
    run_proof_contract,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_contract_baseline,
)
import pytest


def test_one_unit_can_hold_the_full_relation() -> None:
    evidence = evidence_in_text(
        "Ansvaret är begränsat till arvodet, dock inte vid brott mot sekretessåtagandet."
    )
    assert evidence["relation_complete_in_unit"] is True
    assert evidence["components"]["liability_cap"]
    assert evidence["components"]["exception"]
    assert evidence["components"]["secrecy_breach"]
    assert proposed_status(evidence, missing_coverage_parts=()) == COMPLETE_IN_UNIT


def test_reference_without_secrecy_stays_unresolved() -> None:
    evidence = evidence_in_text(
        "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot punkt 4."
    )
    assert evidence["reference"] == "4"
    assert evidence["status"] == UNRESOLVED_REFERENCE
    assert proposed_status(evidence, missing_coverage_parts=()) == UNRESOLVED_REFERENCE


def test_split_coverage_group_still_needs_a_hop() -> None:
    evidence = evidence_in_text(
        "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess."
    )
    assert evidence["relation_complete_in_unit"] is True
    assert (
        proposed_status(evidence, missing_coverage_parts=("the cap sentence",))
        == NEEDS_COMPLEMENTARY
    )


def test_current_rule_is_hop_and_is_not_applied_to_v3() -> None:
    assert current_status() == CURRENT_HOP
    assert RETRIEVAL_CONCLUSIONS["proof_contract_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_gap_frozen"] is True
    frozen = load_proof_contract_baseline()
    assert frozen["id"] == "phase2-proof-contract-v1"
    assert frozen["headline"]["proposed_complete_at_first_signal"] == 6
    assert frozen["proof_contract_applied_to_v3"] is False


def test_proof_contract_on_frozen_carveout() -> None:
    c8 = Path("data/jev-liability-secrecy-carveout-C8.json")
    if not c8.is_file():
        pytest.skip("local carve-out C@8 is not in the checkout")
    payload = run_proof_contract()
    assert payload["coverage_v3_unchanged"] is True
    assert payload["does_not_claim_saved_classifications"] is True
    assert payload["current_complete_at_first_signal"] == 0
    assert payload["proposed_complete_at_first_signal"] == 6
    assert payload["needs_complementary"] == ["Avtal_46_SaaS_avtal.docx"]
    assert "Avtal_49_IT_drift_hostingavtal.docx" in payload["unresolved_references"]
    assert payload["control_none_complete"] is True
    by_path = {row["relative_path"]: row for row in payload["positives"]}
    assert by_path["Avtal_05_Konsultavtal.docx"]["proposed"] == COMPLETE_IN_UNIT
    assert by_path["Avtal_46_SaaS_avtal.docx"]["proposed"] == NEEDS_COMPLEMENTARY
