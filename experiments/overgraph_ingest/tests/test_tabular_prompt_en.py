from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_prompt_en_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.evaluate import CORRECT_NOT_FOUND, FALSE_ANSWER, TRUE_ANSWER
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompt_dev import ERROR_CELLS, SELECTION_CELLS
from overgraph_ingest.tabular.prompt_en import (
    PROMPT_SV,
    TABULAR_PROMPT_EN_PATH,
    freeze_tabular_prompt_en,
    pick_language,
    run_tabular_prompt_en,
    write_tabular_prompt_en_baseline,
)
from overgraph_ingest.tabular.prompts import ENGLISH_QUESTIONS, PROMPT_P0, PROMPT_P0_EN
from overgraph_ingest.tabular.search import DEFAULT_K
from tests.test_tabular_prompt_dev import RecordingJev
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
PROMPT_DEV = ROOT / "baselines" / "phase2-tabular-prompt-dev-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
SEL_PATH, SEL_Q = SELECTION_CELLS[0]
ERR_PATH, ERR_Q = ERROR_CELLS[0]
GOLD_TEXT = "Avtalet förlängs automatiskt med tolv månader."


def _row(prompt: str, outcome: str) -> dict[str, object]:
    return {
        "prompt": prompt,
        "outcome": outcome,
        "role": "selection",
        "full_success": outcome in {TRUE_ANSWER, CORRECT_NOT_FOUND},
    }


def _units() -> list:
    rows = []
    for path in (SEL_PATH, ERR_PATH):
        rows.extend(
            _unit(f"{path}-noise-{index}", path, "Ingen sekretess.", sequence=index)
            for index in range(1, 5)
        )
        rows.append(_unit(f"{path}-gold", path, GOLD_TEXT, sequence=5))
    return rows


def _golds() -> list[RetrievalGold]:
    ids = {SEL_Q, ERR_Q}
    return [
        RetrievalGold(
            id=question_id,
            query=USER_QUESTIONS[question_id],
            classify_question="Innehåller texten bestämmelsen?",
            relevant_units=[GoldSpan(SEL_PATH, "förlängs automatiskt")]
            if question_id == SEL_Q
            else [GoldSpan("other.docx", "saknas")],
            hard_negatives=[],
        )
        for question_id in ids
    ]


def _signals() -> dict[str, object]:
    cells = []
    for path, question_id in ((SEL_PATH, SEL_Q), (ERR_PATH, ERR_Q)):
        keys = [f"{path}-noise-{index}" for index in range(1, 5)] + [f"{path}-gold"]
        cells.append(
            {
                "relative_path": path,
                "question_id": question_id,
                "hybrid": {"candidate_keys": keys},
                "dense": {"candidate_keys": list(reversed(keys))},
            }
        )
    return {"cells": cells}


def _reference() -> dict[str, object]:
    scored = []
    for path, question_id, role, outcome, status in (
        (SEL_PATH, SEL_Q, "selection", TRUE_ANSWER, "ANSWERED"),
        (ERR_PATH, ERR_Q, "error", FALSE_ANSWER, "ANSWERED"),
    ):
        for list_name in ("hybrid", "dense"):
            scored.append(
                {
                    "relative_path": path,
                    "question_id": question_id,
                    "prompt": PROMPT_P0,
                    "role": role,
                    "list": list_name,
                    "status": status,
                    "outcome": outcome,
                    "full_success": outcome == TRUE_ANSWER,
                    "gold_positive": role == "selection",
                    "answer_correct": outcome == TRUE_ANSWER,
                    "citation_relevant": outcome == TRUE_ANSWER,
                    "citation_grounded": True,
                    "recall@3": 0.0,
                    "recall@5": 1.0,
                    "recall@10": 1.0,
                    "navigation_successes": 0,
                    "navigation_failures": 0,
                    "jev_calls": 1,
                    "cerebras_calls": 0,
                    "cell_seconds": 0.3,
                    "retrieve_seconds": 0.0,
                    "classify_seconds": 0.0,
                    "navigate_seconds": 0.0,
                    "answer_seconds": 0.3,
                }
            )
    return {"scored": scored, "selection": {}, "errors": {}, "by_prompt": {}, "usage": {}}


def test_default_questions_stay_swedish() -> None:
    assert USER_QUESTIONS["auto-renewal"].startswith("Förlängs")
    assert ENGLISH_QUESTIONS["auto-renewal"].startswith("Does the")
    assert set(ENGLISH_QUESTIONS) == set(USER_QUESTIONS)
    assert P0_STATUS_INSTRUCTIONS.startswith("{question}")
    assert DEFAULT_K == 5


def test_pick_language_rejects_a_true_answer_collapse() -> None:
    picked = pick_language(
        {
            PROMPT_SV: [_row(PROMPT_SV, TRUE_ANSWER), _row(PROMPT_SV, CORRECT_NOT_FOUND)],
            PROMPT_P0_EN: [
                _row(PROMPT_P0_EN, CORRECT_NOT_FOUND),
                _row(PROMPT_P0_EN, CORRECT_NOT_FOUND),
            ],
        }
    )
    assert picked["prompt"] == PROMPT_SV
    assert picked["reason"] == "english_lost_true_answers"
    assert picked["default_unchanged"] is True


def test_english_questions_are_sent_to_jev() -> None:
    jev = RecordingJev()
    payload = run_tabular_prompt_en(
        units=_units(),
        structures={},
        golds=_golds(),
        jev=jev,
        signals=_signals(),
        cells=((SEL_PATH, SEL_Q), (ERR_PATH, ERR_Q)),
        reference=_reference(),
    )
    assert payload["prior_instructions_were_already_english"] is True
    assert payload["default_question_language_unchanged"] is True
    assert payload["default_prompt_unchanged"] is True
    assert jev.calls == 4
    assert any(ENGLISH_QUESTIONS[SEL_Q] in text for text in jev.instructions)
    assert all(USER_QUESTIONS[SEL_Q] not in text for text in jev.instructions)
    assert payload["picked"]["default_unchanged"] is True


def test_prompt_en_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert PROMPT_DEV.is_file()
    assert C8.is_file()
    before = {
        "v1": TABULAR_V1.read_bytes(),
        "dev": PROMPT_DEV.read_bytes(),
        "c8": C8.read_bytes(),
    }
    payload = {
        "headline": {"picked": PROMPT_SV},
        "picked": {"prompt": PROMPT_SV, "default_unchanged": True},
        "selection": {},
        "errors": {},
        "by_prompt": {},
        "changed_from_swedish": [],
        "holdout_not_run": True,
        "swedish_questions": dict(USER_QUESTIONS),
        "english_questions": dict(ENGLISH_QUESTIONS),
        "error_cells": [],
        "selection_cells": [],
        "cells": [],
        "scored": [],
        "usage": {},
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-prompt-en-v1.json"
    write_tabular_prompt_en_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_prompt_en_baseline(payload, target)
    frozen = freeze_tabular_prompt_en(payload)
    assert frozen["id"] == "phase2-tabular-prompt-en-v1"
    assert frozen["prior_instructions_were_already_english"] is True
    assert frozen["default_question_language_unchanged"] is True
    assert frozen["does_not_replace_tabular_prompt_dev"] is True
    assert TABULAR_V1.read_bytes() == before["v1"]
    assert PROMPT_DEV.read_bytes() == before["dev"]
    assert C8.read_bytes() == before["c8"]
    assert TABULAR_PROMPT_EN_PATH != PROMPT_DEV
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_dev_picked"] == "P0"
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_en"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_en_did_not_beat_swedish"] is True
    assert RETRIEVAL_CONCLUSIONS["default_question_language_unchanged"] is True


def test_frozen_english_questions_did_not_beat_swedish() -> None:
    frozen = load_tabular_prompt_en_baseline()
    assert frozen["id"] == "phase2-tabular-prompt-en-v1"
    assert frozen["prior_instructions_were_already_english"] is True
    assert frozen["default_question_language_unchanged"] is True
    assert frozen["picked"]["prompt"] == PROMPT_SV
    assert frozen["headline"]["selection_true_answers"] == {
        PROMPT_SV: 10,
        PROMPT_P0_EN: 10,
    }
    assert frozen["headline"]["selection_false_answers"] == {
        PROMPT_SV: 0,
        PROMPT_P0_EN: 0,
    }
    assert frozen["headline"]["error_false_answers"] == {
        PROMPT_SV: 12,
        PROMPT_P0_EN: 14,
    }
    assert frozen["headline"]["uncertain"] == {PROMPT_SV: 0, PROMPT_P0_EN: 0}
    assert len(frozen["cells"]) == 42
    paths = {row["relative_path"] for row in frozen["changed_from_swedish"]}
    assert paths == {
        "Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx",
        "Avtal_36_Underleverantorsavtal.docx",
    }
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_en_added_false_answers"] is True
