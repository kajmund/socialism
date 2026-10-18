from pathlib import Path

import pytest

from overgraph_ingest.coverage.blind_carveout import (
    BLIND_BASELINE_ID,
    GOLD_ZIP,
    freeze_blind_carveout_baseline,
    run_blind_carveout,
)
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_blind_carveout_baseline,
)


@pytest.mark.skipif(not GOLD_ZIP.is_file(), reason="blind gold zip is not in the checkout")
def test_seen_detectors_miss_every_blind_yes() -> None:
    payload = run_blind_carveout()
    assert payload["yes_count"] == 53
    assert payload["yes_link"] == 0
    assert payload["yes_claim_form"] == 0
    assert payload["no_link"] == 0
    assert payload["yes_multi_clause"] == 34
    assert payload["uncertain_link"] == ["avtal_138", "avtal_173"]
    assert payload["gold_is_synthetic"] is True
    assert payload["yes_wording"]["no_secrecy_word"] == 28
    assert payload["yes_wording"]["has_sekretess"] == 7
    assert payload["live_false_completes_not_in_workspace"] is True


@pytest.mark.skipif(not Path("baselines/phase2-blind-carveout-gold-v1.json").is_file(), reason="baseline missing")
def test_blind_carveout_baseline_is_frozen() -> None:
    frozen = load_blind_carveout_baseline()
    assert frozen["id"] == BLIND_BASELINE_ID
    assert frozen["gold_is_synthetic"] is True
    assert frozen["headline"]["yes_link"] == 0
    assert frozen["headline"]["yes_claim_form"] == 0
    assert frozen["headline"]["uncertain_link"] == ["avtal_138", "avtal_173"]
    assert RETRIEVAL_CONCLUSIONS["seen_detectors_miss_blind_yes"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_blind_carveout_baseline(run_blind_carveout())["headline"]["yes_link"] == 0
