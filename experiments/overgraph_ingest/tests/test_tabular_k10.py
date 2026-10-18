from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_k10_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.cells import VARIANT_B, VARIANT_K
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND
from overgraph_ingest.tabular.evaluate import MISS, TRUE_ANSWER
from overgraph_ingest.tabular.gold import QUESTION_IDS, USER_QUESTIONS
from overgraph_ingest.tabular.k10 import (
    TABULAR_K10_PATH,
    freeze_tabular_k10,
    run_tabular_k10,
    write_tabular_k10_baseline,
)
from overgraph_ingest.tabular.search import DEFAULT_K
from tests.test_tabular_review import ScriptedJev, _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
CITATION = ROOT / "baselines" / "phase2-tabular-citation-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
PATH = "Avtal_05_Konsultavtal.docx"
GOLD_TEXT = "Avtalet förlängs automatiskt med tolv månader."


def _units() -> list:
    rows = []
    for index in range(1, 6):
        rows.append(
            _unit(
                f"strong-{index}",
                PATH,
                "Ingen sekretess och ingen förlängning.",
                sequence=index,
                dense=[1.0, 0.0],
                sparse=[(1, 1.0)],
            )
        )
    rows.append(
        _unit(
            "gold",
            PATH,
            GOLD_TEXT,
            sequence=6,
            dense=[0.4, 0.0],
            sparse=[(1, 0.2)],
        )
    )
    for index in range(7, 11):
        rows.append(
            _unit(
                f"weak-{index}",
                PATH,
                "Punkt om annat.",
                sequence=index,
                dense=[0.1, 0.0],
                sparse=[(2, 1.0)],
            )
        )
    return rows


def _golds() -> list[RetrievalGold]:
    return [
        RetrievalGold(
            id=question_id,
            query=USER_QUESTIONS[question_id],
            classify_question="Innehåller texten bestämmelsen?",
            relevant_units=[GoldSpan(PATH, "förlängs automatiskt")]
            if question_id == "auto-renewal"
            else [],
            hard_negatives=[],
        )
        for question_id in QUESTION_IDS
    ]


def _queries() -> dict[str, tuple[list[float], list[tuple[int, float]]]]:
    return {question_id: ([1.0, 0.0], [(1, 1.0)]) for question_id in QUESTION_IDS}


def _frozen_b_rows() -> list[dict[str, object]]:
    rows = []
    for question_id in QUESTION_IDS:
        gold = question_id == "auto-renewal"
        rows.append(
            {
                "document_id": "Avtal_05_Konsultavtal",
                "relative_path": PATH,
                "question_id": question_id,
                "variant": VARIANT_B,
                "status": NOT_FOUND,
                "outcome": MISS if gold else "correct_not_found",
                "full_success": not gold,
                "answer_correct": not gold,
                "citation_relevant": False,
                "gold_positive": gold,
                "seed_has_gold": False,
                "recall@3": 0.0,
                "recall@5": 0.0,
                "recall@10": 1.0 if gold else 0.0,
                "navigation_successes": 0,
                "navigation_failures": 0,
                "jev_calls": 0,
                "cerebras_calls": 0,
                "cell_seconds": 0.0,
                "retrieve_seconds": 0.0,
                "classify_seconds": 0.0,
                "navigate_seconds": 0.0,
                "answer_seconds": 0.0,
            }
        )
    return rows


def test_default_tabular_k_stays_five() -> None:
    assert DEFAULT_K == 5


def test_k10_recovers_gold_outside_top_five() -> None:
    units = _units()
    payload = run_tabular_k10(
        documents=(PATH,),
        golds=_golds(),
        units=units,
        structures={},
        queries=_queries(),
        jev=ScriptedJev(),
        frozen={"scored": _frozen_b_rows()},
        citation={
            "missing_cells": [
                {"relative_path": PATH, "question_id": "auto-renewal"}
            ]
        },
    )
    cells = [row for row in payload["cells"] if row["question_id"] == "auto-renewal"]
    assert len(cells) == 1
    cell = cells[0]
    assert cell["variant"] == VARIANT_K
    assert cell["retrieval"]["k"] == 10
    assert "gold" not in cell["retrieval"]["candidate_keys"][:5]
    assert "gold" in cell["retrieval"]["candidate_keys"][:10]
    assert cell["status"] == ANSWERED
    scored = payload["scored"][0]
    assert scored["question_id"] == "auto-renewal"
    assert scored["outcome"] == TRUE_ANSWER
    assert scored["seed_has_gold"] is True
    assert payload["no_navigation"] is True
    assert payload["default_k_unchanged"] is True
    assert payload["recovered"]["recovered_cells"] == 1
    assert payload["recovered"]["present_at_k10"] == 1
    assert payload["does_not_replace_tabular_v1"] is True


def test_k10_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert CITATION.is_file()
    assert C8.is_file()
    before_v1 = TABULAR_V1.read_bytes()
    before_citation = CITATION.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "headline": {"k10_cell_accuracy": 0.0},
        "versus": {},
        "k10": {},
        "reference": {},
        "recovered": {},
        "cost": {},
        "cells": [],
        "scored": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-k10-v1.json"
    write_tabular_k10_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_k10_baseline(payload, target)
    frozen = freeze_tabular_k10(payload)
    assert frozen["quality_reference"] == VARIANT_B
    assert frozen["k"] == 10
    assert frozen["reference_k"] == 5
    assert frozen["default_k_unchanged"] is True
    assert frozen["does_not_replace_tabular_v1"] is True
    assert frozen["navigation_not_changed"] is True
    assert TABULAR_V1.read_bytes() == before_v1
    assert CITATION.read_bytes() == before_citation
    assert C8.read_bytes() == before_c8
    assert TABULAR_K10_PATH != TABULAR_V1
    assert RETRIEVAL_CONCLUSIONS["tabular_model_comparisons"] == "paused"
    assert RETRIEVAL_CONCLUSIONS["do_not_build_tabular_navigation"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_second_run_100_not_started"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_k10_did_not_beat_k5"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_k"] == 5
    assert RETRIEVAL_CONCLUSIONS["do_not_widen_tabular_k"] is True


def test_frozen_tabular_k10_did_not_beat_k5() -> None:
    frozen = load_tabular_k10_baseline()
    assert frozen["id"] == "phase2-tabular-k10-v1"
    assert frozen["k"] == 10
    assert frozen["reference_k"] == 5
    assert frozen["default_k_unchanged"] is True
    assert frozen["headline"]["k10_cell_accuracy"] == 0.73
    assert frozen["headline"]["cell_accuracy"]["B"] == 0.78
    assert frozen["headline"]["recovered_missing_gold"] == 4
    assert frozen["headline"]["new_gold_negative_false_answers"] == 9
    assert frozen["versus"]["k_vs_b_cell_accuracy"] < 0
    assert len(frozen["cells"]) == 100
    assert {row["variant"] for row in frozen["cells"]} == {VARIANT_K}
