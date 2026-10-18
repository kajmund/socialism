from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from overgraph_ingest.jev.client import HttpJevClient
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_status_v2_repeats_baseline,
)
from overgraph_ingest.tabular.contract import ANSWERED, UNCERTAIN
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, PROMPT_P0_V2_D, SHARP_QUESTIONS, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.status_v2 import STATUS_V2_PATH
from overgraph_ingest.tabular.status_v2_cases import (
    EVAL_CASES,
    HARD_NEG,
    HARD_NEG_SPLIT,
    HOLDOUT_NEG,
    HOLDOUT_SPLIT,
    NAMED_EXCLUSION_NEEDLES,
    StatusCase,
)
from overgraph_ingest.tabular.status_v2_repeats import (
    REPEATS_ID,
    freeze_tabular_status_v2_repeats,
    jev_has_temperature,
    prompt_scored_eval_cases,
    run_tabular_status_v2_repeats,
    write_tabular_status_v2_repeats_baseline,
)
from tests.test_tabular_prompt_dev import RecordingJev
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
STATUS_V2 = ROOT / "baselines" / "phase2-tabular-status-v2.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
PATH = "Avtal_31_Leveransavtal.docx"


def test_jev_has_no_temperature_parameter() -> None:
    assert "temperature" not in inspect.signature(HttpJevClient.ask).parameters
    assert jev_has_temperature() is False


def test_unused_hard_neg_match_named_exclusions() -> None:
    assert set(HARD_NEG_SPLIT) == {case.case_id for case in HARD_NEG}
    assert all(value.startswith("in_distribution:") for value in HARD_NEG_SPLIT.values())
    asked = " ".join(SHARP_QUESTIONS.values()).lower()
    assert "vite" in asked
    assert "tills vidare" in asked
    assert "avtalets eget innehåll" in asked


def test_holdout_is_outside_eval_and_named_exclusions() -> None:
    eval_ids = {case.case_id for case in EVAL_CASES}
    assert not {case.case_id for case in HOLDOUT_NEG} & eval_ids
    assert set(HOLDOUT_SPLIT) == {case.case_id for case in HOLDOUT_NEG}
    assert all(value.startswith("unseen:") for value in HOLDOUT_SPLIT.values())
    for case in HOLDOUT_NEG:
        blob = " ".join(case.nearby_contains).lower()
        for needle in NAMED_EXCLUSION_NEEDLES:
            assert needle not in blob, f"{case.case_id} still names {needle}"


def test_repeats_d_five_times_and_does_not_change_default_p0(tmp_path: Path) -> None:
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
    units = [
        _unit("gold", PATH, "Ansvaret är begränsat till köpeskillingen.", sequence=1),
        _unit("near", PATH, "Franchisetagaren har rätt att förlänga.", sequence=2),
        _unit("n1", PATH, "Parter.", sequence=3),
        _unit("n2", PATH, "Bakgrund.", sequence=4),
        _unit("n3", PATH, "Tillämplig lag.", sequence=5),
    ]
    scored = StatusCase(
        case_id="unit-eval",
        relative_path=PATH,
        question_id="liability-cap",
        role="hard_pos",
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="begränsat till köpeskillingen",
        candidate_keys=("gold", "near", "n1", "n2", "n3"),
    )
    holdout = StatusCase(
        case_id="holdout:Avtal_35:auto-renewal",
        relative_path=PATH,
        question_id="auto-renewal",
        role="hard_neg",
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("rätt att förlänga",),
        candidate_keys=("gold", "near", "n1", "n2", "n3"),
    )
    jev = RecordingJev()
    payload = run_tabular_status_v2_repeats(
        units=units,
        structures={},
        jev=jev,
        cases=(scored,),
        holdout=(holdout,),
        repeat_n=2,
        write_table=False,
        signals={"cells": []},
    )
    assert payload["default_prompt_unchanged"] is True
    assert payload["does_not_overwrite_status_v2"] is True
    assert payload["jev_has_temperature_parameter"] is False
    assert payload["unused_hard_neg_are_in_distribution"] is True
    assert payload["step"] == PROMPT_P0_V2_D
    assert jev.calls == 4
    assert all("närliggande utdrag är aldrig ANSWERED" in text for text in jev.instructions)
    assert payload["eval_spread"]["true_answered"]["values"] == [1, 1]
    assert payload["eval_spread"]["false_answered"]["values"] == [0, 0]
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_status_v2_unused_hard_neg_are_in_distribution"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_status_v2_holdout_exclusions_unseen"] is True


def test_repeats_freeze_does_not_overwrite_status_v2(tmp_path: Path) -> None:
    before = STATUS_V2.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "headline": {},
        "eval_spread": {},
        "holdout_spread": {},
        "eval_cases": [],
        "holdout_cases": [],
        "exclusion_provenance": {},
        "hard_neg_split": {},
        "holdout_split": {},
        "cells": [],
        "scored": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-status-v2-repeats.json"
    write_tabular_status_v2_repeats_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_status_v2_repeats_baseline(payload, target)
    with pytest.raises(ValueError, match="must not overwrite"):
        write_tabular_status_v2_repeats_baseline(payload, STATUS_V2_PATH)
    frozen = freeze_tabular_status_v2_repeats(payload)
    assert frozen["id"] == REPEATS_ID
    assert frozen["default_prompt_unchanged"] is True
    assert frozen["does_not_overwrite_status_v2"] is True
    assert frozen["unused_hard_neg_are_in_distribution"] is True
    assert STATUS_V2.read_bytes() == before
    assert C8.read_bytes() == before_c8
    assert STATUS_V2_PATH.exists()
    assert len(prompt_scored_eval_cases()) == 23


def test_frozen_repeats_did_not_generalize() -> None:
    frozen = load_tabular_status_v2_repeats_baseline()
    assert frozen["id"] == REPEATS_ID
    assert frozen["default_prompt_unchanged"] is True
    assert frozen["does_not_overwrite_status_v2"] is True
    assert frozen["unused_hard_neg_are_in_distribution"] is True
    assert frozen["jev_has_temperature_parameter"] is False
    assert frozen["eval_spread"]["true_answered"]["values"] == [11, 11, 11, 11, 11]
    assert frozen["eval_spread"]["false_answered"]["values"] == [0, 0, 0, 0, 0]
    assert frozen["eval_spread"]["unstable_cells"] == []
    assert frozen["holdout_spread"]["false_answered"]["values"] == [1, 1, 1, 1, 1]
    assert frozen["holdout_spread"]["cells_with_false_answered"] == [
        "holdout:Avtal_92:liability-cap"
    ]
    assert RETRIEVAL_CONCLUSIONS["tabular_status_v2_repeats"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_status_v2_d_did_not_generalize"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
