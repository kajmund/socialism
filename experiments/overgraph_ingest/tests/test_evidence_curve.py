import pytest

from overgraph_ingest.coverage.evidence_curve import (
    DEFAULT_V3,
    EVIDENCE_CONTRACTS,
    coverage_curve,
    ranking_curve,
    run_evidence_curves,
)
from overgraph_ingest.jev.baseline import load_official_classify_baseline
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_evidence_curve_baseline,
    load_first_evidence_baseline,
)


def test_first_verified_evidence_is_frozen() -> None:
    frozen = load_first_evidence_baseline()
    official = load_official_classify_baseline()
    assert frozen["id"] == "phase2-first-verified-evidence"
    assert frozen["do_not_overwrite"] is True
    assert frozen["do_not_optimize_first_yes"] is True
    assert frozen["does_not_replace_c8"] is True
    assert frozen["id"] != official["id"]
    by_id = {row["gold_id"]: row for row in frozen["golds"]}
    assert by_id["auto-renewal"]["judgments_until_first_verified"] == 1
    assert by_id["liability-cap"]["false_yes_before_first_verified"] == 3
    assert RETRIEVAL_CONCLUSIONS["do_not_optimize_first_yes"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert RETRIEVAL_CONCLUSIONS["evidence_contracts"] == EVIDENCE_CONTRACTS


def test_ranking_curve_counts_unique_verified_documents() -> None:
    curve = ranking_curve(
        {
            "gold_id": "t",
            "runs": [
                {
                    "variant": "C@8",
                    "concurrency": 8,
                    "batch_size": 1,
                    "wall_judgments": [
                        {
                            "rank": 1,
                            "key": "a",
                            "relative_path": "one.docx",
                            "gold_label": "relevant",
                            "predicted": "YES",
                        },
                        {
                            "rank": 2,
                            "key": "b",
                            "relative_path": "neg.docx",
                            "gold_label": "hard_negative",
                            "predicted": "YES",
                        },
                        {
                            "rank": 3,
                            "key": "c",
                            "relative_path": "one.docx",
                            "gold_label": "relevant",
                            "predicted": "YES",
                        },
                        {
                            "rank": 4,
                            "key": "d",
                            "relative_path": "two.docx",
                            "gold_label": "relevant",
                            "predicted": "YES",
                        },
                    ],
                }
            ],
        }
    )
    assert curve["verified_positive_documents"] == 2
    assert [row["classified"] for row in curve["increments"]] == [1, 4]
    assert curve["increments"][1]["cost_since_previous"] == 3
    assert curve["checkpoints"] == [
        {"classified": 10, "verified_positive_documents": 2},
        {"classified": 25, "verified_positive_documents": 2},
        {"classified": 50, "verified_positive_documents": 2},
    ]


def test_coverage_curve_holds_last_known_count_at_checkpoints() -> None:
    curve = coverage_curve(
        {
            "gold_id": "t",
            "budgets": [
                {
                    "variant": "B5",
                    "documents_expected": 13,
                    "documents_found": 13,
                    "budget_exhausted_documents": 56,
                    "unresolved_relevant_documents": [],
                    "timeline": [
                        {"phase": "global", "classified": 50, "documents_found": 8},
                        {"phase": "pass_1", "classified": 128, "documents_found": 10},
                        {"phase": "pass_2", "classified": 196, "documents_found": 13},
                    ],
                }
            ],
        }
    )
    assert curve["budget_exhausted_is_not_absent"] is True
    by_mark = {row["classified"]: row["verified_positive_documents"] for row in curve["checkpoints"]}
    assert by_mark[10] is None
    assert by_mark[50] == 8
    assert by_mark[100] == 8
    assert by_mark[150] == 10
    assert by_mark[200] == 13
    assert curve["increments"][2]["new_documents"] == 3
    assert curve["increments"][2]["cost_per_new_document"] == 68 / 3
    assert curve["last_new_positive_at"] == 196
    assert curve["classifications_after_last_new_positive"] == 0


def test_evidence_curve_baseline_is_frozen() -> None:
    frozen = load_evidence_curve_baseline()
    assert frozen["id"] == "phase2-evidence-curve-v1"
    assert frozen["do_not_overwrite"] is True
    assert frozen["do_not_optimize_first_yes"] is True
    assert frozen["budget_exhausted_is_not_absent"] is True
    assert frozen["ranking_checkpoints"]["confidentiality"]["10"] == 1
    assert frozen["workspace_checkpoints"]["confidentiality"]["200"] == 13
    assert frozen["workspace_tail"]["auto-renewal"]["classifications_after_last_new_positive"] == 363
    assert frozen["workspace_tail"]["confidentiality"]["classifications_after_last_new_positive"] == 158


def test_evidence_curves_read_frozen_c8_and_coverage_v3() -> None:
    if not DEFAULT_V3.is_file():
        pytest.skip("local Coverage v3 run is not in the checkout")
    payload = run_evidence_curves()
    assert payload["do_not_optimize_first_yes"] is True
    assert payload["does_not_replace_c8"] is True
    by_id = {row["gold_id"]: row for row in payload["golds"]}
    auto = by_id["auto-renewal"]
    assert auto["ranking"]["increments"][0]["classified"] == 1
    assert auto["workspace"]["checkpoints"][-1]["verified_positive_documents"] == 19
    assert auto["workspace"]["unresolved_relevant_documents"] == [
        "Avtal_18_Hyresavtal_bostad.docx"
    ]
    secret = by_id["confidentiality"]
    assert secret["ranking"]["increments"][0]["classified"] == 1
    assert secret["workspace"]["verified_positive_documents"] == 13
    assert secret["workspace"]["budget_exhausted_documents"] == 56
