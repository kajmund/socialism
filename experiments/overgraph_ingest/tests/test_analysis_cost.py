from overgraph_ingest.coverage.analysis_cost import analysis_cost_from_c8
from overgraph_ingest.jev.baseline import load_official_classify_baseline


def test_analysis_cost_finds_first_verified_positive_on_c8() -> None:
    payload = load_official_classify_baseline()
    cost = analysis_cost_from_c8(payload)
    assert cost["gold_id"] == "auto-renewal"
    assert cost["first_relevant_rank"] == 1
    assert cost["first_verified_positive_rank"] == 1
    assert cost["judgments_until_first_verified"] == 1
    assert cost["false_yes_before_first_verified"] == 0
    assert cost["budget_exhausted_is_not_absent"] is True


def test_analysis_cost_counts_work_before_first_verified() -> None:
    payload = {
        "gold_id": "t",
        "runs": [
            {
                "variant": "C@8",
                "concurrency": 8,
                "batch_size": 1,
                "wall_judgments": [
                    {
                        "rank": 1,
                        "key": "hn",
                        "relative_path": "neg.docx",
                        "gold_label": "hard_negative",
                        "predicted": "YES",
                    },
                    {
                        "rank": 2,
                        "key": "other",
                        "relative_path": "other.docx",
                        "gold_label": "other",
                        "predicted": "UNCERTAIN",
                    },
                    {
                        "rank": 3,
                        "key": "hit",
                        "relative_path": "yes.docx",
                        "gold_label": "relevant",
                        "predicted": "YES",
                    },
                ],
            }
        ],
    }
    cost = analysis_cost_from_c8(payload)
    assert cost["first_verified_positive_rank"] == 3
    assert cost["judgments_until_first_verified"] == 3
    assert cost["false_yes_before_first_verified"] == 1
    assert cost["hard_or_watch_before_first_verified"] == 1
    assert cost["uncertain_before_first_verified"] == 1
