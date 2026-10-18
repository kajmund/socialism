from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.jev.candidates import context_from_units
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_direct_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.cells import VARIANT_B, VARIANT_D, run_cell
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND
from overgraph_ingest.tabular.direct import (
    TABULAR_DIRECT_PATH,
    freeze_tabular_direct,
    run_tabular_direct,
    write_tabular_direct_baseline,
)
from overgraph_ingest.tabular.evaluate import MISS, TRUE_ANSWER
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.search import DEFAULT_K
from tests.test_tabular_review import ScriptedJev, _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
K10 = ROOT / "baselines" / "phase2-tabular-k10-v1.json"
K10_ERRORS = ROOT / "baselines" / "phase2-tabular-k10-errors-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
PATH = "Avtal_05_Konsultavtal.docx"
GOLD_TEXT = "Avtalet förlängs automatiskt med tolv månader."


def _units() -> list:
    rows = [
        _unit(
            f"noise-{index}",
            PATH,
            "Ingen sekretess och ingen förlängning.",
            sequence=index,
            dense=[1.0, 0.0],
            sparse=[(1, 1.0)],
        )
        for index in range(1, 5)
    ]
    rows.append(
        _unit(
            "gold",
            PATH,
            GOLD_TEXT,
            sequence=5,
            dense=[0.1, 0.0],
            sparse=[(2, 1.0)],
        )
    )
    return rows


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="auto-renewal",
        query=USER_QUESTIONS["auto-renewal"],
        classify_question="Innehåller texten bestämmelsen?",
        relevant_units=[GoldSpan(PATH, "förlängs automatiskt")],
        hard_negatives=[],
    )


def _frozen_cell() -> dict[str, object]:
    keys = [f"noise-{index}" for index in range(1, 5)] + ["gold"]
    return {
        "document_id": "Avtal_05_Konsultavtal",
        "relative_path": PATH,
        "question_id": "auto-renewal",
        "question": USER_QUESTIONS["auto-renewal"],
        "variant": VARIANT_B,
        "status": NOT_FOUND,
        "retrieval": {
            "k": 5,
            "candidate_keys": keys,
            "recall@3": 0.0,
            "recall@5": 1.0,
            "recall@10": 1.0,
        },
    }


def _frozen_scored() -> dict[str, object]:
    return {
        "document_id": "Avtal_05_Konsultavtal",
        "relative_path": PATH,
        "question_id": "auto-renewal",
        "variant": VARIANT_B,
        "status": NOT_FOUND,
        "outcome": MISS,
        "full_success": False,
        "answer_correct": False,
        "citation_relevant": False,
        "citation_grounded": False,
        "gold_positive": True,
        "recall@3": 0.0,
        "recall@5": 1.0,
        "recall@10": 1.0,
        "navigation_successes": 0,
        "navigation_failures": 0,
        "jev_calls": 6,
        "cerebras_calls": 0,
        "cell_seconds": 1.6,
        "retrieve_seconds": 0.1,
        "classify_seconds": 1.2,
        "navigate_seconds": 0.0,
        "answer_seconds": 0.3,
    }


def test_default_tabular_k_stays_five() -> None:
    assert DEFAULT_K == 5


def test_direct_skips_classify_and_reuses_frozen_keys() -> None:
    jev = ScriptedJev()
    payload = run_tabular_direct(
        units=_units(),
        structures={},
        golds=[_gold()],
        jev=jev,
        expected_cells=1,
        frozen={"cells": [_frozen_cell()], "scored": [_frozen_scored()]},
    )
    assert payload["classify_skipped"] is True
    assert payload["judgments_passed_to_answer"] is False
    assert payload["hypothesis"] == "A"
    assert payload["same_five_candidates"] is True
    assert payload["no_navigation"] is True
    assert payload["no_new_retrieval"] is True
    assert payload["default_k_unchanged"] is True
    cells = payload["cells"]
    assert len(cells) == 1
    cell = cells[0]
    assert cell["variant"] == VARIANT_D
    assert cell["retrieval"]["candidate_keys"] == [
        "noise-1",
        "noise-2",
        "noise-3",
        "noise-4",
        "gold",
    ]
    assert cell["status"] == ANSWERED
    assert cell["source_unit_ids"] == ["gold"]
    assert cell["jev_calls"] == 1
    assert cell["classify_seconds"] == 0.0
    assert jev.calls == 1
    assert payload["scored"][0]["outcome"] == TRUE_ANSWER
    assert payload["headline"]["direct_jev_calls"] == 1
    assert payload["headline"]["reference_jev_calls"] == 6
    assert payload["versus"]["d_vs_b_jev_calls"] == -5


def test_variant_d_makes_one_jev_call() -> None:
    units = _units()
    jev_b = ScriptedJev()
    jev_d = ScriptedJev()
    shared = {
        "relative_path": PATH,
        "question_id": "auto-renewal",
        "user_question": USER_QUESTIONS["auto-renewal"],
        "classify_question": "Innehåller texten bestämmelsen?",
        "units": units,
        "context": context_from_units(units, {}),
        "dense_query": [1.0, 0.0],
        "sparse_query": [(1, 1.0)],
        "relevant_keys": {"gold"},
        "cerebras": None,
        "jev_model": "jev-latest",
        "timeout_seconds": 1.0,
    }
    two_step = run_cell(variant=VARIANT_B, jev=jev_b, **shared)
    direct = run_cell(variant=VARIANT_D, jev=jev_d, **shared)
    assert two_step.jev_calls == 6
    assert jev_b.calls == 6
    assert direct.jev_calls == 1
    assert jev_d.calls == 1
    assert direct.classify_seconds == 0.0


def test_direct_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert K10.is_file()
    assert K10_ERRORS.is_file()
    assert C8.is_file()
    before_v1 = TABULAR_V1.read_bytes()
    before_k10 = K10.read_bytes()
    before_errors = K10_ERRORS.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "headline": {"direct_cell_accuracy": 0.0},
        "versus": {},
        "direct": {},
        "reference": {},
        "cost": {},
        "cells": [],
        "scored": [],
        "paired": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-direct-v1.json"
    write_tabular_direct_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_direct_baseline(payload, target)
    frozen = freeze_tabular_direct(payload)
    assert frozen["id"] == "phase2-tabular-direct-v1"
    assert frozen["quality_reference"] == VARIANT_B
    assert frozen["k"] == 5
    assert frozen["classify_skipped"] is True
    assert frozen["judgments_passed_to_answer"] is False
    assert frozen["does_not_replace_tabular_v1"] is True
    assert frozen["does_not_replace_tabular_k10"] is True
    assert frozen["navigation_not_changed"] is True
    assert TABULAR_V1.read_bytes() == before_v1
    assert K10.read_bytes() == before_k10
    assert K10_ERRORS.read_bytes() == before_errors
    assert C8.read_bytes() == before_c8
    assert TABULAR_DIRECT_PATH != TABULAR_V1
    assert RETRIEVAL_CONCLUSIONS["tabular_direct_hypothesis"] == "A"
    assert RETRIEVAL_CONCLUSIONS["do_not_feed_classify_into_answer"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_b"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_direct"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_direct_held_quality"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_direct_saved_jev_calls"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_direct_did_not_beat_b"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_two_step_vs_direct"] is False
    assert RETRIEVAL_CONCLUSIONS["tabular_performance_reference"] == "jev_d"
    assert RETRIEVAL_CONCLUSIONS["tabular_historical_two_step"] == "jev_b"
    assert RETRIEVAL_CONCLUSIONS["tabular_pipeline"] == "document_local_top5_answer_cell"
    assert RETRIEVAL_CONCLUSIONS["do_not_test_hypothesis_b"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_b"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_promise_local_jev_latency"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_right_five"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_not_more_model_steps"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_widen_tabular_k"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_start_new_embedding"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_k"] == 5


def test_frozen_tabular_direct_held_quality() -> None:
    frozen = load_tabular_direct_baseline()
    assert frozen["id"] == "phase2-tabular-direct-v1"
    assert frozen["k"] == 5
    assert frozen["classify_skipped"] is True
    assert frozen["judgments_passed_to_answer"] is False
    assert frozen["same_five_candidates"] is True
    assert frozen["headline"]["direct_cell_accuracy"] == 0.78
    assert frozen["headline"]["direct_answer_accuracy"] == 0.81
    assert frozen["headline"]["cell_accuracy"]["B"] == 0.78
    assert frozen["headline"]["direct_jev_calls"] == 100
    assert frozen["headline"]["reference_jev_calls"] == 600
    assert frozen["versus"]["d_vs_b_cell_accuracy"] == 0.0
    assert frozen["versus"]["d_vs_b_jev_calls"] == -500
    assert frozen["headline"]["same_status"] == 97
    assert len(frozen["cells"]) == 100
    assert {row["variant"] for row in frozen["cells"]} == {VARIANT_D}
    assert all(row["jev_calls"] == 1 for row in frozen["cells"])
    assert frozen["default_k_unchanged"] is True
    assert frozen["does_not_replace_tabular_v1"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_quality_reference"] == "jev_b"
    assert RETRIEVAL_CONCLUSIONS["tabular_performance_reference"] == "jev_d"
