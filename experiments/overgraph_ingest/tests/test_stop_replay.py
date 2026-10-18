from overgraph_ingest.coverage.stop_replay import (
    INVESTIGATION_COMPLETE,
    INVESTIGATION_PARTIAL,
    replay_gold,
    run_stop_replay,
    stop_at,
)
from overgraph_ingest.coverage.evidence_curve import DEFAULT_V3
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_workspace_stop_baseline,
)

import pytest


def _timeline() -> list[dict[str, object]]:
    return [
        {
            "phase": "global",
            "classified": 50,
            "documents_found": 7,
            "unresolved_relevant": ["a.docx", "b.docx"],
            "status_counts": {
                "UNEXAMINED": 61,
                "NO_EVIDENCE_YET": 31,
                "NEEDS_ANALYSIS": 8,
            },
        },
        {
            "phase": "pass_1",
            "classified": 150,
            "documents_found": 7,
            "unresolved_relevant": [],
            "status_counts": {
                "NO_EVIDENCE_YET": 93,
                "EVIDENCE_FOUND": 7,
            },
        },
        {
            "phase": "pass_5",
            "classified": 482,
            "documents_found": 7,
            "unresolved_relevant": [],
            "status_counts": {
                "BUDGET_EXHAUSTED": 92,
                "EVIDENCE_FOUND": 8,
            },
        },
    ]


def test_stop_keeps_jev_yes_and_complete_evidence_apart() -> None:
    early = stop_at(_timeline(), 50, 7, 482, "COMPOSITE")
    later = stop_at(_timeline(), 150, 7, 482, "COMPOSITE")
    assert early["jev_yes_documents"] == 7
    assert early["complete_evidence_documents"] == 5
    assert early["investigation_result"] == INVESTIGATION_PARTIAL
    assert early["saved_classifications"] == 432
    assert early["unresolved_kinds"]["composite_incomplete"] == 2
    assert later["jev_yes_documents"] == 7
    assert later["complete_evidence_documents"] == 7
    assert later["next_complete_evidence"] is None
    assert early["next_complete_evidence"]["classifications_until_next"] == 100
    assert early["next_jev_yes"] is None


def test_stop_between_phases_holds_last_observed_state() -> None:
    row = stop_at(_timeline(), 100, 7, 482, "COMPOSITE")
    assert row["observed_classified"] == 50
    assert row["phase"] == "global"
    assert row["replay_of_observed_path"] is True


def test_complete_requires_every_document_decided() -> None:
    finished = [
        {
            "phase": "done",
            "classified": 10,
            "documents_found": 2,
            "unresolved_relevant": [],
            "status_counts": {"EVIDENCE_FOUND": 2, "VERIFIED_ABSENT": 1},
        }
    ]
    row = stop_at(finished, 50, 2, 10, "EXISTS")
    assert row["investigation_result"] == INVESTIGATION_COMPLETE
    assert row["unresolved_documents"] == 0


def test_budget_exhausted_is_unresolved_not_absent() -> None:
    row = stop_at(_timeline(), 482, 7, 482, "COMPOSITE")
    assert row["investigation_result"] == INVESTIGATION_PARTIAL
    assert row["unresolved_documents"] == 92
    assert row["budget_exhausted_is_not_absent"] is True


def test_replay_gold_does_not_choose_a_stop_rule() -> None:
    payload = replay_gold(
        {
            "gold_id": "carveout",
            "proof_kind": "COMPOSITE",
            "budgets": [
                {
                    "variant": "B5",
                    "documents_expected": 7,
                    "classified": 482,
                    "unresolved_relevant_documents": [],
                    "budget_exhausted_documents": 92,
                    "timeline": _timeline(),
                }
            ],
        }
    )
    assert payload["replay_of_observed_path"] is True
    assert [row["stop_budget"] for row in payload["stops"]] == [50, 100, 150, 200, 300]


def test_workspace_stop_rule_is_not_chosen() -> None:
    frozen = load_workspace_stop_baseline()
    assert frozen["id"] == "phase2-workspace-stop-replay-v1"
    assert frozen["no_new_stop_rule"] is True
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["golds"]["liability-secrecy-carveout"]["jev_yes"]["50"] == 7
    assert frozen["golds"]["liability-secrecy-carveout"]["complete_evidence"]["50"] == 0
    assert frozen["golds"]["liability-secrecy-carveout"]["complete_evidence"]["150"] == 7
    assert RETRIEVAL_CONCLUSIONS["workspace_stop_rule"] == "not_chosen"
    assert RETRIEVAL_CONCLUSIONS["investigation_results"] == (
        "COMPLETE",
        "PARTIAL",
        "FAILED",
    )


def test_stop_replay_reads_coverage_v3() -> None:
    if not DEFAULT_V3.is_file():
        pytest.skip("local Coverage v3 run is not in the checkout")
    payload = run_stop_replay()
    assert payload["coverage_v3_unchanged"] is True
    assert payload["no_new_stop_rule"] is True
    by_id = {row["gold_id"]: row for row in payload["golds"]}
    auto = {row["stop_budget"]: row for row in by_id["auto-renewal"]["stops"]}
    assert auto[50]["jev_yes_documents"] == 19
    assert auto[50]["complete_evidence_documents"] == 19
    assert auto[50]["investigation_result"] == INVESTIGATION_PARTIAL
    carve = {row["stop_budget"]: row for row in by_id["liability-secrecy-carveout"]["stops"]}
    assert carve[50]["jev_yes_documents"] == 7
    assert carve[50]["complete_evidence_documents"] == 0
    assert carve[150]["complete_evidence_documents"] == 7
