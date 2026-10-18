from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_status_v2_baseline,
)
from overgraph_ingest.tabular.contract import ANSWERED, CellResult, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import (
    PROMPT_P0,
    PROMPT_P0_V2,
    PROMPT_P0_V2_B,
    PROMPT_P0_V2_D,
    SHARP_QUESTIONS,
    instruction_for,
    questions_for,
)
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.status_v2 import (
    FALSE_ABSTENTION,
    FALSE_ANSWERED,
    RETRIEVAL_ERROR,
    TRUE_ANSWERED,
    freeze_tabular_status_v2,
    run_tabular_status_v2,
    score_status,
    write_tabular_status_v2_baseline,
)
from overgraph_ingest.tabular.status_v2_cases import (
    EVAL_CASES,
    HARD_NEG,
    HARD_POS,
    NEARBY_IS_UNCERTAIN,
    StatusCase,
)
from tests.test_tabular_prompt_dev import RecordingJev
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
PROMPT_DEV = ROOT / "baselines" / "phase2-tabular-prompt-dev-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
PATH = "Avtal_31_Leveransavtal.docx"
GOLD = "4f66b90f733f1c58f1ad063949e62751e0a8cdb95136d506e2572791cde82a02"
NEAR = "296eecedc2703fc48609e6818c44aef8f4f0a8f781efc8d146beb074f74d39d7"


def _result(status: str, sources: list[str] | None = None, excerpt: str = "") -> CellResult:
    return CellResult(
        document_id="Avtal_31_Leveransavtal",
        relative_path=PATH,
        question_id="liability-cap",
        question=USER_QUESTIONS["liability-cap"],
        variant=PROMPT_P0_V2,
        status=status,
        answer=excerpt,
        source_unit_ids=sources or [],
        sources=[],
        retrieval={"candidate_keys": [GOLD, NEAR]},
    )


def test_default_p0_stays_the_short_english_instruction() -> None:
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert "Beslut:" not in P0_STATUS_INSTRUCTIONS
    assert "Beslut:" in instruction_for(PROMPT_P0_V2)
    assert "Beslut:" not in instruction_for(PROMPT_P0_V2_B)
    assert DEFAULT_K == 5
    assert NEARBY_IS_UNCERTAIN is True


def test_sharp_questions_exclude_nearby_terms_on_true_and_false_cells() -> None:
    asked = questions_for(PROMPT_P0_V2_D)
    assert asked == SHARP_QUESTIONS
    assert all("Räknas inte" in text for text in asked.values())
    assert "vite" in asked["liability-cap"]
    assert "tills vidare" in asked["auto-renewal"]
    assert questions_for(PROMPT_P0) == USER_QUESTIONS


def test_eval_is_not_only_the_known_errors() -> None:
    roles = {case.role for case in EVAL_CASES}
    assert "hard_pos" in roles
    assert "hard_neg" in roles
    assert "selection_true" in roles
    assert len(HARD_POS) >= 5
    assert len(HARD_NEG) >= 5
    unused = {case.relative_path for case in HARD_POS + HARD_NEG}
    assert "Avtal_31_Leveransavtal.docx" in unused
    assert "Avtal_38_Projektavtal_fast_pris.docx" in unused


def test_score_status_separates_nearby_answered_from_true_and_retrieval() -> None:
    case = StatusCase(
        case_id="t",
        relative_path=PATH,
        question_id="liability-cap",
        role="hard_pos",
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="köpeskillingen",
    )
    assert (
        score_status(case, _result(ANSWERED, [GOLD], "tak"), {GOLD})["outcome"]
        == TRUE_ANSWERED
    )
    assert (
        score_status(case, _result(ANSWERED, [NEAR], "vite"), {GOLD})["outcome"]
        == "wrong_excerpt"
    )
    assert score_status(case, _result(NOT_FOUND), {GOLD})["outcome"] == FALSE_ABSTENTION
    nearby = StatusCase(
        case_id="n",
        relative_path=PATH,
        question_id="liability-cap",
        role="hard_neg",
        list_name="constructed",
        expected_status=UNCERTAIN,
    )
    assert score_status(nearby, _result(ANSWERED, [NEAR], "vite"), set())["outcome"] == FALSE_ANSWERED
    assert score_status(nearby, _result(UNCERTAIN), set())["outcome"] == "true_uncertain"
    retrieval = StatusCase(
        case_id="r",
        relative_path=PATH,
        question_id="confidentiality",
        role="retrieval_error",
        list_name="hybrid",
        expected_status=ANSWERED,
        prompt_scored=False,
    )
    assert score_status(retrieval, _result(ANSWERED, [NEAR]), set())["outcome"] == RETRIEVAL_ERROR


def test_status_v2_sends_the_new_instruction(tmp_path: Path) -> None:
    units = [
        _unit("gold", PATH, "Ansvaret är begränsat till köpeskillingen.", sequence=1),
        _unit("near", PATH, "Vite med 0,5 procent.", sequence=2),
        _unit("n1", PATH, "Parter.", sequence=3),
        _unit("n2", PATH, "Bakgrund.", sequence=4),
        _unit("n3", PATH, "Tillämplig lag.", sequence=5),
    ]
    case = StatusCase(
        case_id="unit",
        relative_path=PATH,
        question_id="liability-cap",
        role="hard_pos",
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="begränsat till köpeskillingen",
        candidate_keys=("gold", "near", "n1", "n2", "n3"),
    )
    jev = RecordingJev()
    payload = run_tabular_status_v2(
        units=units,
        structures={},
        jev=jev,
        cases=(case,),
        steps=(PROMPT_P0_V2,),
        repeat_n=1,
        permutations=False,
        write_table=False,
        reference={"cells": []},
        signals={"cells": []},
    )
    assert payload["default_prompt_unchanged"] is True
    assert payload["nearby_is_uncertain"] is True
    assert jev.calls == 1
    assert any("närliggande utdrag är aldrig ANSWERED" in text for text in jev.instructions)
    assert payload["scored"][0]["outcome"] == TRUE_ANSWERED


def test_status_v2_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    before_dev = PROMPT_DEV.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "headline": {},
        "acceptance": {},
        "by_step": {},
        "cases": [],
        "cells": [],
        "scored": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-status-v2.json"
    write_tabular_status_v2_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_status_v2_baseline(payload, target)
    frozen = freeze_tabular_status_v2(payload)
    assert frozen["id"] == "phase2-tabular-status-v2"
    assert frozen["default_prompt_unchanged"] is True
    assert frozen["nearby_is_uncertain"] is True
    assert PROMPT_DEV.read_bytes() == before_dev
    assert C8.read_bytes() == before_c8
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_prompt_dev_picked"] == "P0"
    assert RETRIEVAL_CONCLUSIONS["tabular_status_v2"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_status_v2_d_met_acceptance"] is True


def test_frozen_status_v2_d_met_acceptance() -> None:
    frozen = load_tabular_status_v2_baseline()
    assert frozen["id"] == "phase2-tabular-status-v2"
    assert frozen["nearby_is_uncertain"] is True
    assert frozen["default_prompt_unchanged"] is True
    assert frozen["headline"]["false_answered"][PROMPT_P0] == 7
    assert frozen["headline"]["false_answered"][PROMPT_P0_V2_D] == 0
    assert frozen["headline"]["true_answered"][PROMPT_P0_V2_D] == 11
    assert frozen["headline"]["false_abstention"][PROMPT_P0_V2_D] == 0
    assert frozen["acceptance"]["false_answered_09_17_zero"][PROMPT_P0_V2] is True
    assert frozen["acceptance"]["false_answered_09_17_zero"][PROMPT_P0_V2_D] is True
    assert frozen["acceptance"]["permutations"][PROMPT_P0_V2_D]["cited_gold"] == 5
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
