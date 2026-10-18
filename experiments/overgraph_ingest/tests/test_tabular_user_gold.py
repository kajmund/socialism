from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_question_gold_baseline,
    load_tabular_user_gold_baseline,
)
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.evaluate import CORRECT_NOT_FOUND, FALSE_ANSWER, MISS, TRUE_ANSWER
from overgraph_ingest.tabular.gold import QUESTION_IDS, SELECTED_DOCUMENTS, USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.user_eval import (
    compare_user_gold,
    score_user_cell,
    write_user_gold_baseline,
)
from overgraph_ingest.tabular.user_gold import (
    SILENT,
    YES,
    assert_user_gold_complete,
    user_cell_map,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "retrieval_gold"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
AUTO = GOLD / "auto-renewal.json"
CONF = GOLD / "confidentiality.json"
DIRECT = ROOT / "baselines" / "phase2-tabular-direct-v1.json"


def _cell(path: str, question_id: str, status: str, answer: str = "") -> dict[str, object]:
    return {
        "document_id": path.replace(".docx", ""),
        "relative_path": path,
        "question_id": question_id,
        "status": status,
        "answer": answer,
        "sources": [{"excerpt": answer}] if answer else [],
        "variant": "D",
    }


def test_user_gold_covers_every_cell_and_keeps_old_gold() -> None:
    assert_user_gold_complete()
    golds = user_cell_map()
    assert len(golds) == len(QUESTION_IDS) * len(SELECTED_DOCUMENTS)
    assert golds[("Avtal_07_Sekretessavtal_omsesidigt.docx", "confidentiality")].polarity == YES
    assert golds[("Avtal_30_Ramavtal_tjanster.docx", "confidentiality")].polarity == YES
    assert golds[("Avtal_18_Hyresavtal_bostad.docx", "auto-renewal")].polarity == "until_notice"
    assert any(
        "tills vidare" in span.contains
        for span in golds[("Avtal_18_Hyresavtal_bostad.docx", "auto-renewal")].answers
    )
    conf13 = golds[("Avtal_13_Avgangsvederlagsavtal.docx", "confidentiality")]
    assert len(conf13.answers) == 2
    assert golds[("Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx", "liability-cap")].polarity == SILENT
    assert golds[("Avtal_08_Konkurrensforbudsavtal.docx", "confidentiality")].polarity == SILENT
    assert AUTO.read_text(encoding="utf-8").count("tills vidare") >= 1
    assert "Avtal_07_Sekretessavtal_omsesidigt" not in CONF.read_text(encoding="utf-8")


def test_user_gold_does_not_change_questions_or_p0() -> None:
    assert USER_QUESTIONS["notice-period"] == "Vilken uppsägningstid gäller enligt avtalet?"
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert RETRIEVAL_CONCLUSIONS["do_not_retune_gold_to_model"] is True
    assert RETRIEVAL_CONCLUSIONS["historical_cell_accuracy_is_not_user_quality"] is True
    assert RETRIEVAL_CONCLUSIONS["user_question_is_the_contract"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_overwrite_retrieval_gold"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_user_gold"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_e_beat_d_on_user_gold"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_remains_d"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_e_is_next_candidate"] is True


def test_score_accepts_any_listed_span() -> None:
    gold = user_cell_map()[("Avtal_13_Avgangsvederlagsavtal.docx", "confidentiality")]
    first = score_user_cell(
        _cell(gold.relative_path, gold.question_id, ANSWERED, gold.answers[0].contains),
        gold,
    )
    second = score_user_cell(
        _cell(gold.relative_path, gold.question_id, ANSWERED, gold.answers[1].contains),
        gold,
    )
    miss = score_user_cell(_cell(gold.relative_path, gold.question_id, NOT_FOUND), gold)
    wrong = score_user_cell(
        _cell(gold.relative_path, gold.question_id, ANSWERED, "Ansvaret är begränsat"),
        gold,
    )
    assert first["outcome"] == TRUE_ANSWER
    assert second["outcome"] == TRUE_ANSWER
    assert miss["outcome"] == MISS
    assert wrong["outcome"] == FALSE_ANSWER


def test_silent_not_found_is_correct() -> None:
    gold = user_cell_map()[("Avtal_100_Djurkopeavtal.docx", "confidentiality")]
    empty = score_user_cell(_cell(gold.relative_path, gold.question_id, NOT_FOUND), gold)
    invented = score_user_cell(
        _cell(gold.relative_path, gold.question_id, ANSWERED, "tystnadsplikt"),
        gold,
    )
    unsure = score_user_cell(_cell(gold.relative_path, gold.question_id, UNCERTAIN), gold)
    assert empty["outcome"] == CORRECT_NOT_FOUND
    assert invented["outcome"] == FALSE_ANSWER
    assert unsure["outcome"] == "abstention"


def test_frozen_variants_against_user_gold() -> None:
    before = AUTO.read_bytes()
    payload = compare_user_gold()
    assert payload["does_not_run_jev"] is True
    assert payload["does_not_change_retrieval_gold"] is True
    assert payload["historical_cell_accuracy_is_not_user_quality"] is True
    assert payload["ranking_flipped"] is True
    assert payload["historical_passage_gold"]["D"]["cell_accuracy"] == 0.78
    assert payload["headline"]["D"] == 0.84
    assert payload["headline"]["E"] == 0.90
    assert payload["headline"]["K"] == 0.90
    assert AUTO.read_bytes() == before
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    frozen = load_tabular_user_gold_baseline()
    assert frozen["headline"] == payload["headline"]
    assert frozen["does_not_run_jev"] is True
    diagnosis = load_tabular_question_gold_baseline()
    assert diagnosis["historical_cell_accuracy_is_not_user_quality"] is True
    assert diagnosis["user_question_is_the_contract"] is True


def test_user_gold_baseline_is_write_once(tmp_path: Path) -> None:
    payload = compare_user_gold()
    target = tmp_path / "user-gold.json"
    write_user_gold_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_user_gold_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_user_gold_baseline(payload, C8)
    with pytest.raises(FileExistsError):
        write_user_gold_baseline(payload, DIRECT)
