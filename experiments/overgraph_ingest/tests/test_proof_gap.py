from overgraph_ingest.coverage.proof_gap import ranking_gaps, run_proof_gap, workspace_gap
from overgraph_ingest.coverage.evidence_curve import DEFAULT_V3
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_gap_baseline,
)
from overgraph_ingest.retrieval.gold import CoverageGroup, RetrievalGold

import pytest


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="carveout",
        query="q",
        proof_kind="COMPOSITE",
        relevant_units=[],
        hard_negatives=[],
        document_gold=("a.docx", "b.docx"),
        coverage_groups=[
            CoverageGroup("a.docx", ("ansvarsbegransning", "sekretessundantag")),
        ],
    )


def test_ranking_gap_keeps_discovery_and_proof_apart() -> None:
    payload = {
        "runs": [
            {
                "variant": "C@8",
                "concurrency": 8,
                "batch_size": 1,
                "wall_judgments": [
                    {
                        "rank": 2,
                        "key": "yes",
                        "relative_path": "a.docx",
                        "gold_label": "relevant",
                        "predicted": "YES",
                        "text": "sekretessundantag. previous has the missing cap",
                    },
                    {
                        "rank": 9,
                        "key": "ref",
                        "relative_path": "watch.docx",
                        "gold_label": "other",
                        "predicted": "UNCERTAIN",
                        "text": "brott mot punkt 4.",
                    },
                ],
                "coverage_groups": {
                    "groups": [
                        {
                            "relative_path": "a.docx",
                            "members": [{"neighbor_has_other_span": True}],
                            "graph_note": "neighbor hop",
                        }
                    ]
                },
            }
        ]
    }
    gap = ranking_gaps(_gold(), payload)
    by_path = {row["relative_path"]: row for row in gap["documents"]}
    assert by_path["a.docx"]["missing_complementary_passage"] is True
    assert by_path["a.docx"]["hop_possible"] is True
    assert by_path["a.docx"]["work_kind"] == "proof_completion"
    assert by_path["b.docx"]["work_kind"] == "discovery"
    assert gap["missing_complementary_passage"] == 1
    assert gap["hop_possible"] == 1
    assert gap["open_references"][0]["reference"] == "4"


def test_workspace_gap_counts_classifications_between_yes_and_complete() -> None:
    gap = workspace_gap(
        {
            "gold_id": "carveout",
            "proof_kind": "COMPOSITE",
            "budgets": [
                {
                    "documents_expected": 7,
                    "hop_fetches": 12,
                    "action_counts": {"global": 50, "in_document": 420, "hop:PREVIOUS": 8},
                    "timeline": [
                        {
                            "phase": "global",
                            "classified": 50,
                            "documents_found": 7,
                            "unresolved_relevant": ["a.docx"],
                        },
                        {
                            "phase": "pass_1",
                            "classified": 150,
                            "documents_found": 7,
                            "unresolved_relevant": [],
                        },
                    ],
                }
            ],
        }
    )
    assert gap["first_all_jev_yes_at"] == 50
    assert gap["first_complete_evidence_at"] == 150
    assert gap["classifications_between_yes_and_complete"] == 100
    assert gap["hop_actions"] == {"hop:PREVIOUS": 8}


def test_proof_gap_baseline_is_frozen() -> None:
    frozen = load_proof_gap_baseline()
    assert frozen["id"] == "phase2-proof-gap-v1"
    assert frozen["no_new_controller"] is True
    assert frozen["headline"]["composite_documents_missing_complementary_passage"] == 1
    assert frozen["headline"]["avtal_46_hop_relation"] == "PREVIOUS"
    assert frozen["headline"]["workspace_classifications_between_yes_and_complete"] == 100


def test_frozen_workspace_conclusions_do_not_pick_a_stop_rule() -> None:
    assert RETRIEVAL_CONCLUSIONS["workspace_stop_rule"] == "not_chosen"
    assert RETRIEVAL_CONCLUSIONS["partial_must_be_disclosed"] is True
    assert RETRIEVAL_CONCLUSIONS["jev_yes_is_not_legal_evidence"] is True
    assert RETRIEVAL_CONCLUSIONS["no_general_stop_budget"] is True
    assert RETRIEVAL_CONCLUSIONS["problem_is_work_allocation"] is True
    assert RETRIEVAL_CONCLUSIONS["work_kinds"] == ("discovery", "proof_completion")
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"


def test_proof_gap_reads_frozen_runs() -> None:
    if not DEFAULT_V3.is_file():
        pytest.skip("local Coverage v3 run is not in the checkout")
    payload = run_proof_gap()
    assert payload["no_new_controller"] is True
    by_id = {row["gold_id"]: row for row in payload["golds"]}
    carve = by_id["liability-secrecy-carveout"]
    assert carve["ranking"]["missing_complementary_passage"] == 1
    assert carve["ranking"]["hop_possible"] == 1
    avtal_46 = next(
        row
        for row in carve["ranking"]["documents"]
        if str(row["relative_path"]).startswith("Avtal_46_")
    )
    assert avtal_46["first_signal_rank"] == 2
    assert avtal_46["parts_found"] == 1
    assert avtal_46["parts_needed"] == 2
    assert avtal_46["hop_relation"] == "PREVIOUS"
    assert carve["workspace"]["classifications_between_yes_and_complete"] == 100
