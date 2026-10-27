"""Contract for the frozen research-ordering measurement (docs/architecture/
research-ordering-measurement-spec.md). Loads the frozen baseline and pins the
measured relations — including the negative outcome of the decision rule, so a
semantic-only ordering change cannot be re-proposed without new evidence."""

from __future__ import annotations

import json
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[1] / "baselines" / "research-ordering-v1.json"

STRATEGIES = ("dense", "sparse", "hybrid", "union_rrf", "union_pool")
RELEVANT = {
    "auto-renewal": 20,
    "notice-period": 13,
    "liability-cap": 34,
    "confidentiality": 13,
    "liability-secrecy-carveout": 7,
}


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def scans(baseline: dict, question: str, strategy: str) -> int | None:
    return baseline["questions"][question]["scans"][strategy]


def test_baseline_is_complete_and_matches_gold() -> None:
    baseline = load_baseline()
    assert baseline["id"] == "research-ordering-v1"
    questions = baseline["questions"]
    assert set(questions) == set(RELEVANT)
    for question, relevant in RELEVANT.items():
        entry = questions[question]
        assert entry["relevant"] == relevant, question
        assert set(entry["scans"]) == set(STRATEGIES), question


def test_decision_rule_not_met_is_pinned() -> None:
    """The >=2x hybrid-vs-sparse threshold was not reached: hybrid beats
    sparse by >=2x on exactly one question, and pure lexical wins outright
    on carveout. Pinned so the negative outcome survives."""
    baseline = load_baseline()
    beats_by_2x = 0
    for question in RELEVANT:
        sparse = scans(baseline, question, "sparse")
        hybrid = scans(baseline, question, "hybrid")
        if sparse is not None and hybrid is not None and hybrid * 2 <= sparse:
            beats_by_2x += 1
    assert beats_by_2x == 1, beats_by_2x
    carveout_sparse = scans(baseline, "liability-secrecy-carveout", "sparse")
    carveout_hybrid = scans(baseline, "liability-secrecy-carveout", "hybrid")
    assert carveout_sparse == 10 and carveout_hybrid == 15


def test_semantic_alone_is_insufficient() -> None:
    """Pure dense never reaches full recall within k=100 on three of five
    questions — semantic-only ordering is not a production candidate."""
    baseline = load_baseline()
    missed = sum(
        1 for question in RELEVANT if scans(baseline, question, "dense") is None
    )
    assert missed == 3, missed


def test_union_pool_is_robust() -> None:
    """The union-pool fusion is the only strategy that reaches full recall
    within k=100 on every question."""
    baseline = load_baseline()
    for question in RELEVANT:
        assert scans(baseline, question, "union_pool") is not None, question


def test_no_strategy_beats_the_oracle_floor() -> None:
    """Sanity: no measured ordering can scan fewer units than the gold count."""
    baseline = load_baseline()
    for question, relevant in RELEVANT.items():
        for strategy in STRATEGIES:
            value = scans(baseline, question, strategy)
            if value is not None:
                assert value >= relevant, (question, strategy)
