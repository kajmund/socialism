from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_prompt_dev_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.evaluate import CORRECT_NOT_FOUND, FALSE_ANSWER, TRUE_ANSWER
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompt_dev import (
    DEV_CELLS,
    ERROR_CELLS,
    SELECTION_CELLS,
    TABULAR_PROMPT_DEV_PATH,
    freeze_tabular_prompt_dev,
    pick_prompt,
    run_tabular_prompt_dev,
    write_tabular_prompt_dev_baseline,
)
from overgraph_ingest.tabular.prompts import INSTRUCTIONS, PROMPT_P0, PROMPT_P1, PROMPT_P2, PROMPT_P3
from overgraph_ingest.tabular.search import DEFAULT_K
from tests.test_tabular_review import ScriptedJev, _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
DIRECT = ROOT / "baselines" / "phase2-tabular-direct-v1.json"
SIGNALS = ROOT / "baselines" / "phase2-tabular-signals-v1.json"
DENSE = ROOT / "baselines" / "phase2-tabular-dense-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
SEL_PATH, SEL_Q = SELECTION_CELLS[0]
ERR_PATH, ERR_Q = ERROR_CELLS[0]
GOLD_TEXT = "Avtalet förlängs automatiskt med tolv månader."


class RecordingJev(ScriptedJev):
    def __init__(self) -> None:
        super().__init__()
        self.instructions: list[str] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        if "status" in questions:
            self.instructions.append(str(questions["status"]["instructions"]))
        return super().ask(
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )


def _row(prompt: str, outcome: str, *, full_success: bool | None = None) -> dict[str, object]:
    success = outcome in {TRUE_ANSWER, CORRECT_NOT_FOUND} if full_success is None else full_success
    return {
        "prompt": prompt,
        "outcome": outcome,
        "role": "selection",
        "full_success": success,
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


def test_p0_is_the_frozen_answer_cell_instruction() -> None:
    assert INSTRUCTIONS[PROMPT_P0] == P0_STATUS_INSTRUCTIONS
    assert "exact substring" in P0_STATUS_INSTRUCTIONS
    assert "Shared topic words" not in P0_STATUS_INSTRUCTIONS


def test_known_errors_are_not_selection_gold() -> None:
    assert set(SELECTION_CELLS) & set(ERROR_CELLS) == set()
    assert len(DEV_CELLS) == 21
    assert len(set(DEV_CELLS)) == 21
    assert DEFAULT_K == 5


def test_pick_prompt_rejects_a_true_answer_collapse() -> None:
    selection = {
        PROMPT_P0: [_row(PROMPT_P0, TRUE_ANSWER), _row(PROMPT_P0, FALSE_ANSWER)],
        PROMPT_P1: [_row(PROMPT_P1, CORRECT_NOT_FOUND), _row(PROMPT_P1, CORRECT_NOT_FOUND)],
        PROMPT_P2: [_row(PROMPT_P2, TRUE_ANSWER), _row(PROMPT_P2, FALSE_ANSWER)],
        PROMPT_P3: [_row(PROMPT_P3, TRUE_ANSWER), _row(PROMPT_P3, CORRECT_NOT_FOUND)],
    }
    picked = pick_prompt(selection)
    assert picked["prompt"] == PROMPT_P3
    assert PROMPT_P1 not in picked["eligible"]
    assert picked["p0_true_answers"] == 1
    assert picked["default_unchanged"] is True


def test_pick_prompt_keeps_p0_when_others_do_not_beat_it() -> None:
    rows = [_row(PROMPT_P0, TRUE_ANSWER), _row(PROMPT_P0, CORRECT_NOT_FOUND)]
    selection = {
        PROMPT_P0: rows,
        PROMPT_P1: [_row(PROMPT_P1, TRUE_ANSWER), _row(PROMPT_P1, FALSE_ANSWER)],
        PROMPT_P2: [_row(PROMPT_P2, TRUE_ANSWER), _row(PROMPT_P2, FALSE_ANSWER)],
        PROMPT_P3: [_row(PROMPT_P3, TRUE_ANSWER), _row(PROMPT_P3, FALSE_ANSWER)],
    }
    picked = pick_prompt(selection)
    assert picked["prompt"] == PROMPT_P0
    assert picked["reason"] == "p0_tied_or_best_on_selection"


def test_prompt_dev_runs_hybrid_and_dense_and_sends_each_instruction() -> None:
    jev = RecordingJev()
    payload = run_tabular_prompt_dev(
        units=_units(),
        structures={},
        golds=_golds(),
        jev=jev,
        signals=_signals(),
        cells=((SEL_PATH, SEL_Q), (ERR_PATH, ERR_Q)),
    )
    assert payload["known_errors_are_not_selection_gold"] is True
    assert payload["default_prompt_unchanged"] is True
    assert payload["default_hybrid_unchanged"] is True
    assert payload["performance_reference"] == "D"
    assert payload["retrieval_baseline"] == "hybrid"
    assert len(payload["cells"]) == 16
    assert {row["variant"] for row in payload["cells"]} == {PROMPT_P0, PROMPT_P1, PROMPT_P2, PROMPT_P3}
    assert {row["list"] for row in payload["scored"]} == {"hybrid", "dense"}
    assert {row["role"] for row in payload["scored"]} == {"selection", "error"}
    assert jev.calls == 16
    assert any("Shared topic words" in text for text in jev.instructions)
    assert any("legal relation" in text for text in jev.instructions)
    assert any("scope must match" in text for text in jev.instructions)
    selection_p0 = [
        row
        for row in payload["scored"]
        if row["prompt"] == PROMPT_P0 and row["role"] == "selection"
    ]
    assert {row["outcome"] for row in selection_p0} == {TRUE_ANSWER}
    assert payload["picked"]["default_unchanged"] is True


def test_prompt_dev_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert DIRECT.is_file()
    assert SIGNALS.is_file()
    assert DENSE.is_file()
    assert C8.is_file()
    before = {
        "v1": TABULAR_V1.read_bytes(),
        "direct": DIRECT.read_bytes(),
        "signals": SIGNALS.read_bytes(),
        "dense": DENSE.read_bytes(),
        "c8": C8.read_bytes(),
    }
    payload = {
        "headline": {"picked": PROMPT_P0},
        "picked": {"prompt": PROMPT_P0, "default_unchanged": True},
        "selection": {},
        "errors": {},
        "by_prompt": {},
        "hypotheses": {},
        "error_cells": [],
        "selection_cells": [],
        "cells": [],
        "scored": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-prompt-dev-v1.json"
    write_tabular_prompt_dev_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_prompt_dev_baseline(payload, target)
    frozen = freeze_tabular_prompt_dev(payload)
    assert frozen["id"] == "phase2-tabular-prompt-dev-v1"
    assert frozen["known_errors_are_not_selection_gold"] is True
    assert frozen["default_prompt_unchanged"] is True
    assert frozen["default_hybrid_unchanged"] is True
    assert frozen["does_not_replace_tabular_direct"] is True
    assert TABULAR_V1.read_bytes() == before["v1"]
    assert DIRECT.read_bytes() == before["direct"]
    assert SIGNALS.read_bytes() == before["signals"]
    assert DENSE.read_bytes() == before["dense"]
    assert C8.read_bytes() == before["c8"]
    assert TABULAR_PROMPT_DEV_PATH != DIRECT
    assert RETRIEVAL_CONCLUSIONS["tabular_performance_reference"] == "jev_d"
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_hybrid"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_dev"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_dev_picked"] == "P0"
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_did_not_beat_p0"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_treat_known_errors_as_quality_gold"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_holdout_not_run"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_k"] == 5


def test_frozen_prompt_dev_keeps_p0() -> None:
    frozen = load_tabular_prompt_dev_baseline()
    assert frozen["id"] == "phase2-tabular-prompt-dev-v1"
    assert frozen["known_errors_are_not_selection_gold"] is True
    assert frozen["default_prompt_unchanged"] is True
    assert frozen["default_hybrid_unchanged"] is True
    assert frozen["holdout_not_run"] is True
    assert frozen["picked"]["prompt"] == PROMPT_P0
    assert frozen["headline"]["picked"] == PROMPT_P0
    assert frozen["headline"]["selection_true_answers"] == {
        PROMPT_P0: 10,
        PROMPT_P1: 10,
        PROMPT_P2: 10,
        PROMPT_P3: 10,
    }
    assert frozen["headline"]["selection_false_answers"] == {
        PROMPT_P0: 0,
        PROMPT_P1: 0,
        PROMPT_P2: 0,
        PROMPT_P3: 0,
    }
    assert frozen["headline"]["error_false_answers"] == {
        PROMPT_P0: 12,
        PROMPT_P1: 11,
        PROMPT_P2: 11,
        PROMPT_P3: 11,
    }
    assert frozen["headline"]["uncertain"] == {
        PROMPT_P0: 0,
        PROMPT_P1: 0,
        PROMPT_P2: 0,
        PROMPT_P3: 0,
    }
    assert len(frozen["cells"]) == 168
    assert {row["relative_path"] for row in frozen["changed_from_p0"]} == {
        "Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx"
    }
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_did_not_fix_avtal_13"] is True
