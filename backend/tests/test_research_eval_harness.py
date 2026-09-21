from copy import deepcopy
from pathlib import Path

import pytest

from app.services.research_eval_harness import STAGES, evaluate_case, load_case

CASE = Path(__file__).parent / "fixtures" / "research_eval" / "36_avtl.json"


def test_golden_36_avtl_passes_all_stages():
    golden, artifacts = load_case(CASE)
    report = evaluate_case(golden, artifacts)
    assert tuple(report) == STAGES
    assert all(row.passed for row in report.values())


@pytest.mark.parametrize(
    "stage,mutate",
    [
        ("plan_coverage", lambda a: a["plan_topics"].remove("consumer_factors")),
        ("source_relevance", lambda a: a["sources"]["prop_1971_20"].update(selected=True)),
        (
            "domain_extraction",
            lambda a: a["domain_results"]["synthetic_positive_case"]["fields"].update(
                adjustment_granted=False
            ),
        ),
        (
            "citation_grounding",
            lambda a: a["domain_results"]["synthetic_positive_case"]["citations"][0].update(
                quote="invented quote"
            ),
        ),
        ("claim_coverage", lambda a: a["claims"].pop(0)),
        ("assessment_completeness", lambda a: a["assessment"].update(completeness="incomplete")),
        ("expert_context", lambda a: a["expert_context"]["claim_ids"].remove("negative")),
    ],
)
def test_reports_regression_at_its_stage(stage, mutate):
    golden, artifacts = load_case(CASE)
    broken = deepcopy(artifacts)
    mutate(broken)
    report = evaluate_case(golden, broken)
    assert not report[stage].passed
    assert report[stage].regressions
