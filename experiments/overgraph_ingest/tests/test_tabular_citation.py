from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_citation_baseline,
)
from overgraph_ingest.tabular.citation import (
    TABULAR_CITATION_PATH,
    classify_citation_failure,
    classify_selection,
    freeze_tabular_citation,
    gold_hit,
    run_tabular_citation,
    write_tabular_citation_baseline,
)
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
TABULAR_QWEN = ROOT / "baselines" / "phase2-tabular-qwen-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "document_id": "Avtal_05_Konsultavtal",
        "relative_path": "Avtal_05_Konsultavtal.docx",
        "question_id": "confidentiality",
        "variant": "B",
        "status": ANSWERED,
        "outcome": "true_answer",
        "full_success": True,
        "citation_relevant": True,
        "gold_positive": True,
        "seed_has_gold": True,
        "recall@3": 1.0,
        "recall@5": 1.0,
        "recall@10": 1.0,
    }
    row.update(overrides)
    return row


def test_gold_hit_is_presence_not_mean() -> None:
    assert gold_hit(1.0) is True
    assert gold_hit(0.5) is True
    assert gold_hit(0.0) is False
    assert gold_hit(None) is False


def test_selection_and_citation_failure_split() -> None:
    assert classify_selection(_row()) == "cited_gold"
    assert (
        classify_selection(_row(citation_relevant=False, outcome="false_answer", full_success=False))
        == "wrong_pick"
    )
    assert (
        classify_selection(
            _row(status=UNCERTAIN, citation_relevant=False, outcome="abstention", full_success=False)
        )
        == "no_answer"
    )
    assert classify_selection(_row(seed_has_gold=False, citation_relevant=False)) is None
    assert (
        classify_citation_failure(
            _row(gold_positive=False, citation_relevant=False, outcome="false_answer")
        )
        == "gold_negative_false_answer"
    )
    assert (
        classify_citation_failure(
            _row(seed_has_gold=False, citation_relevant=False, outcome="false_answer")
        )
        == "missing_gold"
    )
    assert classify_citation_failure(_row()) is None


def test_replay_splits_missing_gold_from_wrong_pick() -> None:
    present = _row()
    missing = _row(
        document_id="Avtal_01_Tillsvidareanstallningsavtal",
        relative_path="Avtal_01_Tillsvidareanstallningsavtal.docx",
        status=NOT_FOUND,
        outcome="miss",
        full_success=False,
        citation_relevant=False,
        seed_has_gold=False,
        **{"recall@3": 0.0, "recall@5": 0.0, "recall@10": 1.0},
    )
    payload = run_tabular_citation(
        review={"scored": [present, missing], "cells": []},
        qwen={"scored": [], "cells": []},
        expected_gold_positive=2,
    )
    assert payload["no_new_model"] is True
    assert payload["no_new_retrieval"] is True
    assert payload["quality_reference"] == "B"
    assert payload["verdict"] == "retrieval_not_selection"
    assert payload["next"] == "document_local_retrieval"
    assert payload["retrieval"]["gold_hit@5"] == 0.5
    assert payload["retrieval"]["gold_hit@10"] == 1.0
    assert payload["retrieval"]["missing_at_k5"] == 1
    assert payload["retrieval"]["recoverable_at_k10"] == 1
    assert payload["variants"]["B"]["source_selection_when_present"] == 1.0
    assert payload["variants"]["B"]["wrong_pick_when_present"] == 0


def test_frozen_tabular_citation_is_retrieval_not_selection() -> None:
    payload = run_tabular_citation()
    retrieval = payload["retrieval"]
    jev = payload["variants"]["B"]
    assert payload["model_comparisons_paused"] is True
    assert retrieval["gold_hit@3_count"] == 19
    assert retrieval["gold_hit@5_count"] == 20
    assert retrieval["gold_hit@10_count"] == 25
    assert retrieval["missing_at_k5"] == 7
    assert retrieval["recoverable_at_k10"] == 5
    assert retrieval["still_missing_at_k10"] == 2
    assert retrieval["missing_are_confidentiality"] is True
    assert retrieval["by_question"]["confidentiality"] == {
        "gold_positive": 8,
        "gold_hit@3": 0,
        "gold_hit@5": 1,
        "gold_hit@10": 6,
        "seed_has_gold": 1,
    }
    assert jev["cited_gold_when_present"] == 20
    assert jev["wrong_pick_when_present"] == 0
    assert jev["citation_accuracy_when_present"] == 1.0
    assert jev["citation_failures"] == {
        "answered_without_gold_citation": 17,
        "gold_negative_false_answer": 14,
        "missing_gold": 3,
        "wrong_pick": 0,
    }
    assert payload["variants"]["C"]["wrong_pick_when_present"] == 0
    assert payload["variants"]["Q"]["wrong_pick_when_present"] == 1
    assert payload["headline"]["jev_cited_gold_whenever_present"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_quality_reference"] == "jev_b"
    assert RETRIEVAL_CONCLUSIONS["tabular_model_comparisons"] == "paused"
    assert RETRIEVAL_CONCLUSIONS["tabular_citation_is_retrieval_not_selection"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_document_local_retrieval"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_test_more_tabular_models"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_build_tabular_navigation"] is True


def test_citation_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert TABULAR_QWEN.is_file()
    assert C8.is_file()
    before_v1 = TABULAR_V1.read_bytes()
    before_qwen = TABULAR_QWEN.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "verdict": "retrieval_not_selection",
        "next": "document_local_retrieval",
        "not_next": ("source_selection", "more_models", "navigation"),
        "headline": {},
        "retrieval": {},
        "variants": {},
        "missing_cells": [],
    }
    target = tmp_path / "phase2-tabular-citation-v1.json"
    write_tabular_citation_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_citation_baseline(payload, target)
    frozen = freeze_tabular_citation(payload)
    assert frozen["quality_reference"] == "B"
    assert frozen["model_comparisons_paused"] is True
    assert frozen["does_not_replace_tabular_v1"] is True
    assert frozen["navigation_not_changed"] is True
    assert TABULAR_V1.read_bytes() == before_v1
    assert TABULAR_QWEN.read_bytes() == before_qwen
    assert C8.read_bytes() == before_c8
    assert TABULAR_CITATION_PATH != TABULAR_V1
    assert RETRIEVAL_CONCLUSIONS["tabular_second_run_100_not_started"] is True


def test_frozen_tabular_citation_baseline_matches_replay() -> None:
    frozen = load_tabular_citation_baseline()
    assert frozen["id"] == "phase2-tabular-citation-v1"
    assert frozen["quality_reference"] == "B"
    assert frozen["verdict"] == "retrieval_not_selection"
    assert frozen["next"] == "document_local_retrieval"
    assert frozen["headline"]["gold_hit@5"] == 20 / 27
    assert frozen["headline"]["missing_gold_at_k5"] == 7
    assert frozen["headline"]["jev_cited_gold_whenever_present"] is True
    assert frozen["retrieval"]["missing_are_confidentiality"] is True
    assert len(frozen["missing_cells"]) == 7
