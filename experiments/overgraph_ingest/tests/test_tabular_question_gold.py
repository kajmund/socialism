from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_probability_baseline,
)
from overgraph_ingest.tabular.gold import USER_QUESTIONS, load_tabular_golds
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.question_gold import (
    FALSE_ANSWER_LABELS,
    review_question_gold,
    write_question_gold_baseline,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "retrieval_gold"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
AUTO = GOLD / "auto-renewal.json"
CONF = GOLD / "confidentiality.json"


def test_user_questions_are_not_the_gold_task() -> None:
    golds = {gold.id: gold for gold in load_tabular_golds(GOLD)}
    assert USER_QUESTIONS["liability-cap"] != golds["liability-cap"].classify_question
    assert USER_QUESTIONS["auto-renewal"] != golds["auto-renewal"].query
    assert "tills vidare" in golds["auto-renewal"].notes
    assert "Annars förlängs avtalet tills vidare." in AUTO.read_text(encoding="utf-8")
    assert "Avtal_07_Sekretessavtal_omsesidigt" not in CONF.read_text(encoding="utf-8")


def test_review_does_not_change_gold_or_p0(tmp_path: Path) -> None:
    before_auto = AUTO.read_bytes()
    before_c8 = C8.read_bytes()
    payload = review_question_gold(write_table=False)
    assert payload["does_not_change_gold"] is True
    assert payload["do_not_retune_gold_to_model"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert AUTO.read_bytes() == before_auto
    assert C8.read_bytes() == before_c8
    assert payload["headline"]["gold_negative_false_answers"] == 14
    assert payload["headline"]["wrong_citation_on_gold_positive"] == 3
    assert payload["counts"]["gold_omission"] == 2
    assert payload["best_aligned"] == "liability-secrecy-carveout"


def test_every_p1_false_answer_has_a_label() -> None:
    frozen = load_tabular_probability_baseline()
    false_keys = {
        (str(row["document_id"]), str(row["question_id"]))
        for row in frozen.get("observations") or []
        if row.get("outcome") == "false_answer"
    }
    assert false_keys == set(FALSE_ANSWER_LABELS)
    assert RETRIEVAL_CONCLUSIONS["tabular_probability_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_build_score_threshold"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_question_gold_alignment"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_retune_gold_to_model"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_probability_kept_for_diagnostics"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_question_gold"] == "diagnosed_v1"
    assert RETRIEVAL_CONCLUSIONS["historical_cell_accuracy_is_not_user_quality"] is True
    assert RETRIEVAL_CONCLUSIONS["user_question_is_the_contract"] is True


def test_question_gold_baseline_is_write_once(tmp_path: Path) -> None:
    payload = review_question_gold(write_table=False)
    target = tmp_path / "question-gold.json"
    write_question_gold_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_question_gold_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_question_gold_baseline(payload, C8)
