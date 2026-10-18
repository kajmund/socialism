from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_dense_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.cells import VARIANT_D, VARIANT_E
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND
from overgraph_ingest.tabular.dense import (
    TABULAR_DENSE_PATH,
    freeze_tabular_dense,
    run_tabular_dense,
    write_tabular_dense_baseline,
)
from overgraph_ingest.tabular.evaluate import MISS, TRUE_ANSWER
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.search import DEFAULT_K
from tests.test_tabular_review import ScriptedJev, _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
DIRECT = ROOT / "baselines" / "phase2-tabular-direct-v1.json"
SIGNALS = ROOT / "baselines" / "phase2-tabular-signals-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
PATH = "Avtal_05_Konsultavtal.docx"
GOLD_TEXT = "Avtalet förlängs automatiskt med tolv månader."


def _units() -> list:
    rows = [
        _unit(f"noise-{index}", PATH, "Ingen sekretess.", sequence=index)
        for index in range(1, 5)
    ]
    rows.append(_unit("gold", PATH, GOLD_TEXT, sequence=5))
    return rows


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="confidentiality",
        query=USER_QUESTIONS["confidentiality"],
        classify_question="Innehåller texten bestämmelsen?",
        relevant_units=[GoldSpan(PATH, "förlängs automatiskt")],
        hard_negatives=[],
    )


def _signals() -> dict[str, object]:
    return {
        "cells": [
            {
                "document_id": "Avtal_05_Konsultavtal",
                "relative_path": PATH,
                "question_id": "confidentiality",
                "question": USER_QUESTIONS["confidentiality"],
                "gold_positive": True,
                "dense": {
                    "candidate_keys": [
                        "gold",
                        "noise-1",
                        "noise-2",
                        "noise-3",
                        "noise-4",
                    ]
                },
            }
        ],
        "recovered": {
            "rows": [{"relative_path": PATH, "question_id": "confidentiality"}]
        },
    }


def _reference() -> dict[str, object]:
    return {
        "scored": [
            {
                "document_id": "Avtal_05_Konsultavtal",
                "relative_path": PATH,
                "question_id": "confidentiality",
                "variant": VARIANT_D,
                "status": NOT_FOUND,
                "outcome": MISS,
                "full_success": False,
                "answer_correct": False,
                "citation_relevant": False,
                "citation_grounded": False,
                "gold_positive": True,
                "recall@3": 0.0,
                "recall@5": 0.0,
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
        ]
    }


def test_default_tabular_k_stays_five() -> None:
    assert DEFAULT_K == 5


def test_dense_answer_recovers_hybrid_confidentiality_miss() -> None:
    jev = ScriptedJev()
    payload = run_tabular_dense(
        units=_units(),
        structures={},
        golds=[_gold()],
        jev=jev,
        expected_cells=1,
        signals=_signals(),
        reference=_reference(),
    )
    assert payload["no_navigation"] is True
    assert payload["default_hybrid_unchanged"] is True
    assert payload["retrieval_treatment"] == "dense"
    assert payload["performance_reference"] == VARIANT_D
    cell = payload["cells"][0]
    assert cell["variant"] == VARIANT_E
    assert cell["retrieval"]["candidate_keys"][0] == "gold"
    assert cell["status"] == ANSWERED
    assert cell["source_unit_ids"] == ["gold"]
    assert cell["jev_calls"] == 1
    assert jev.calls == 1
    assert payload["scored"][0]["outcome"] == TRUE_ANSWER
    assert payload["recovered"]["confidentiality_misses"] == 1
    assert payload["recovered"]["recovered_cells"] == 1
    assert payload["recovered"]["new_gold_negative_false_answers"] == 0


def test_dense_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert DIRECT.is_file()
    assert SIGNALS.is_file()
    assert C8.is_file()
    before_v1 = TABULAR_V1.read_bytes()
    before_direct = DIRECT.read_bytes()
    before_signals = SIGNALS.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "headline": {"dense_cell_accuracy": 0.0},
        "versus": {},
        "dense": {},
        "reference": {},
        "recovered": {},
        "cost": {},
        "cells": [],
        "scored": [],
        "paired": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-dense-v1.json"
    write_tabular_dense_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_dense_baseline(payload, target)
    frozen = freeze_tabular_dense(payload)
    assert frozen["id"] == "phase2-tabular-dense-v1"
    assert frozen["retrieval_treatment"] == "dense"
    assert frozen["retrieval_baseline"] == "hybrid"
    assert frozen["default_hybrid_unchanged"] is True
    assert frozen["does_not_replace_tabular_direct"] is True
    assert TABULAR_V1.read_bytes() == before_v1
    assert DIRECT.read_bytes() == before_direct
    assert SIGNALS.read_bytes() == before_signals
    assert C8.read_bytes() == before_c8
    assert TABULAR_DENSE_PATH != DIRECT
    assert RETRIEVAL_CONCLUSIONS["tabular_performance_reference"] == "jev_d"
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_hybrid"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_dense_answer_cell"] is False
    assert RETRIEVAL_CONCLUSIONS["tabular_dense"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_did_not_beat_hybrid_d"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_recovered_confidentiality_cells"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_added_false_answers"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_assume_recall_is_cell_quality"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_start_new_embedding"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_k"] == 5


def test_frozen_tabular_dense_did_not_beat_hybrid_d() -> None:
    frozen = load_tabular_dense_baseline()
    assert frozen["id"] == "phase2-tabular-dense-v1"
    assert frozen["retrieval_treatment"] == "dense"
    assert frozen["retrieval_baseline"] == "hybrid"
    assert frozen["default_hybrid_unchanged"] is True
    assert frozen["headline"]["dense_cell_accuracy"] == 0.74
    assert frozen["headline"]["reference_cell_accuracy"] == 0.78
    assert frozen["headline"]["confidentiality_recovered"] == 6
    assert frozen["headline"]["confidentiality_misses"] == 7
    assert frozen["headline"]["new_gold_negative_false_answers"] == 10
    assert frozen["versus"]["e_vs_d_cell_accuracy"] < 0
    assert frozen["dense"]["outcomes"]["true_answer"] == 26
    assert frozen["dense"]["outcomes"]["false_answer"] == 24
    assert frozen["reference"]["outcomes"]["true_answer"] == 20
    assert len(frozen["cells"]) == 100
    assert {row["variant"] for row in frozen["cells"]} == {VARIANT_E}
