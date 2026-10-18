from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_dense_errors_baseline,
)
from overgraph_ingest.tabular.dense_errors import (
    GOLD_NARROW,
    TABULAR_DENSE_ERRORS_PATH,
    WRONG_RELATION,
    freeze_tabular_dense_errors,
    run_tabular_dense_errors,
    write_tabular_dense_errors_baseline,
)
from overgraph_ingest.tabular.search import DEFAULT_K

ROOT = Path(__file__).resolve().parents[1]
DIRECT = ROOT / "baselines" / "phase2-tabular-direct-v1.json"
DENSE = ROOT / "baselines" / "phase2-tabular-dense-v1.json"
SIGNALS = ROOT / "baselines" / "phase2-tabular-signals-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"


def test_default_tabular_k_stays_five() -> None:
    assert DEFAULT_K == 5


def test_dense_errors_are_new_units_not_threshold_only() -> None:
    payload = run_tabular_dense_errors()
    assert payload["no_new_model"] is True
    assert payload["no_prompt_change"] is True
    assert payload["default_hybrid_unchanged"] is True
    assert payload["transitions"] == {
        "error_to_correct": 7,
        "correct_to_error": 10,
        "uncertain_to_error": 0,
        "error_to_other_error": 0,
        "correct_to_uncertain": 1,
        "same": 82,
        "other": 0,
        "cells": 100,
    }
    assert payload["headline"]["new_gold_negative_false_answers"] == 10
    assert payload["headline"]["cited_new_dense"] == 9
    assert payload["headline"]["cited_hybrid_already"] == 1
    assert payload["headline"]["gold_narrow"] == 3
    assert payload["headline"]["wrong_relation"] == 7
    assert payload["headline"]["also_k10_false_positive"] == 7
    assert payload["avtal_13"]["same_cite"] is True
    assert payload["avtal_13"]["cited_is_gold"] is False
    assert payload["avtal_13"]["dense_gold_rank"] == 3
    assert {row["label"] for row in payload["rows"]} == {GOLD_NARROW, WRONG_RELATION}
    hybrid_cite = [row for row in payload["rows"] if row["cited_in_hybrid"]]
    assert len(hybrid_cite) == 1
    assert hybrid_cite[0]["relative_path"].startswith("Avtal_09")


def test_dense_errors_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    before_direct = DIRECT.read_bytes()
    before_dense = DENSE.read_bytes()
    before_signals = SIGNALS.read_bytes()
    before_c8 = C8.read_bytes()
    payload = run_tabular_dense_errors()
    target = tmp_path / "phase2-tabular-dense-errors-v1.json"
    write_tabular_dense_errors_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_dense_errors_baseline(payload, target)
    frozen = freeze_tabular_dense_errors(payload)
    assert frozen["id"] == "phase2-tabular-dense-errors-v1"
    assert frozen["performance_reference"] == "D"
    assert frozen["no_prompt_change"] is True
    assert DIRECT.read_bytes() == before_direct
    assert DENSE.read_bytes() == before_dense
    assert SIGNALS.read_bytes() == before_signals
    assert C8.read_bytes() == before_c8
    assert TABULAR_DENSE_ERRORS_PATH != DENSE
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_did_not_beat_hybrid_d"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_hybrid"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_prompt_from_dense_errors"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_errors"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_false_positives_are_new_units"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_threshold_hypothesis_not_measured"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_assume_recall_is_cell_quality"] is True


def test_frozen_tabular_dense_errors_match_replay() -> None:
    frozen = load_tabular_dense_errors_baseline()
    assert frozen["id"] == "phase2-tabular-dense-errors-v1"
    assert frozen["headline"]["correct_to_error"] == 10
    assert frozen["headline"]["error_to_correct"] == 7
    assert frozen["headline"]["cited_new_dense"] == 9
    assert frozen["avtal_13"]["dense_gold_rank"] == 3
    assert frozen["no_prompt_change"] is True
