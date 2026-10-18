from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_holdout_gold_baseline,
)
from overgraph_ingest.tabular.gold import SELECTED_DOCUMENTS, USER_QUESTIONS
from overgraph_ingest.tabular.holdout import (
    EXTRA_CORPUS,
    HOLD_OUT_DOCUMENTS,
    SEEN_OUTSIDE_DIAGNOSTIC,
    select_holdout,
)
from overgraph_ingest.tabular.holdout_eval import (
    refuse_holdout_model_run,
    review_holdout_gold,
    write_holdout_gold_baseline,
)
from overgraph_ingest.tabular.holdout_gold import assert_holdout_gold_complete, holdout_cell_map
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_gold import CELL_MAY_HAVE_MULTIPLE_ANSWERS

ROOT = Path(__file__).resolve().parents[1]
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
AUTO = ROOT / "retrieval_gold" / "auto-renewal.json"


def test_holdout_is_independent_of_the_diagnostic_twenty() -> None:
    assert len(HOLD_OUT_DOCUMENTS) == 20
    assert set(HOLD_OUT_DOCUMENTS).isdisjoint(SELECTED_DOCUMENTS)
    assert set(HOLD_OUT_DOCUMENTS).isdisjoint(SEEN_OUTSIDE_DIAGNOSTIC)
    if EXTRA_CORPUS.is_dir():
        assert select_holdout() == HOLD_OUT_DOCUMENTS


def test_holdout_gold_is_complete_before_models() -> None:
    assert_holdout_gold_complete()
    golds = holdout_cell_map()
    assert len(golds) == 100
    assert golds[("Avtal_15_Bonusavtal.docx", "auto-renewal")].polarity == "no"
    assert golds[("Avtal_48_Mjukvaruutvecklingsavtal.docx", "liability-secrecy-carveout")].polarity == "yes"
    assert golds[("Avtal_81_VD_anstallningsavtal.docx", "auto-renewal")].polarity == "until_notice"
    assert golds[("Avtal_33_Agentavtal.docx", "notice-period")].answers
    assert len(golds[("Avtal_33_Agentavtal.docx", "notice-period")].answers) > 1


def test_holdout_does_not_change_default_or_run_models() -> None:
    before = AUTO.read_bytes()
    payload = review_holdout_gold()
    assert payload["does_not_run_jev"] is True
    assert payload["models_not_run"] is True
    assert payload["default_remains_d"] is True
    assert payload["e_is_next_candidate"] is True
    assert payload["do_not_add_special_rules"] is True
    assert payload["cell_may_have_multiple_answers"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
    assert USER_QUESTIONS["notice-period"].startswith("Vilken uppsägningstid")
    assert AUTO.read_bytes() == before
    with pytest.raises(RuntimeError, match="not run yet"):
        refuse_holdout_model_run()


def test_holdout_conclusions() -> None:
    assert RETRIEVAL_CONCLUSIONS["tabular_default_remains_d"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_e_is_next_candidate"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_switch_default_on_diagnostic_20"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_add_special_rules_for_nearby_errors"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_keep_optimizing_diagnostic_20"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_cell_may_have_multiple_answers"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_holdout"] == "gold_before_models"
    assert RETRIEVAL_CONCLUSIONS["tabular_e_beat_d_on_user_gold"] is True
    assert CELL_MAY_HAVE_MULTIPLE_ANSWERS is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_hybrid"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_k_unchanged"] is True
    frozen = load_tabular_holdout_gold_baseline()
    assert frozen["models_not_run"] is True
    assert frozen["default_remains_d"] is True
    assert frozen["e_is_next_candidate"] is True
    assert len(frozen["documents"]) == 20
    assert len(frozen["cells"]) == 100


def test_holdout_baseline_is_write_once(tmp_path: Path) -> None:
    payload = review_holdout_gold()
    target = tmp_path / "holdout.json"
    write_holdout_gold_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_holdout_gold_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_holdout_gold_baseline(payload, C8)
