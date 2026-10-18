from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_signals_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.cells import VARIANT_B
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.search import DEFAULT_K, document_local_ranks
from overgraph_ingest.tabular.signals import (
    TABULAR_SIGNALS_PATH,
    freeze_tabular_signals,
    run_tabular_signals,
    write_tabular_signals_baseline,
)
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
DIRECT = ROOT / "baselines" / "phase2-tabular-direct-v1.json"
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
            dense=[0.0, 1.0],
            sparse=[(1, 1.0)],
        )
        for index in range(1, 11)
    ]
    rows.append(
        _unit(
            "gold",
            PATH,
            GOLD_TEXT,
            sequence=6,
            dense=[1.0, 0.0],
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


def _frozen() -> dict[str, object]:
    keys = [f"noise-{index}" for index in range(1, 6)]
    return {
        "cells": [
            {
                "document_id": "Avtal_05_Konsultavtal",
                "relative_path": PATH,
                "question_id": "auto-renewal",
                "question": USER_QUESTIONS["auto-renewal"],
                "variant": VARIANT_B,
                "retrieval": {"k": 5, "candidate_keys": keys},
            }
        ]
    }


def test_default_tabular_k_stays_five() -> None:
    assert DEFAULT_K == 5


def test_dense_recovers_gold_that_hybrid_misses() -> None:
    units = _units()
    ranked = document_local_ranks(
        units,
        PATH,
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
    )
    assert ranked["dense"][0].key == "gold"
    assert "gold" not in {hit.key for hit in ranked["hybrid"][:5]}
    payload = run_tabular_signals(
        documents=(PATH,),
        golds=[_gold()],
        units=units,
        structures={},
        queries={"auto-renewal": ([1.0, 0.0], [(1, 1.0)])},
        frozen=_frozen(),
        citation={},
    )
    assert payload["no_answer_cell"] is True
    assert payload["no_new_algorithm"] is True
    assert payload["default_k_unchanged"] is True
    assert payload["strategies"]["dense"]["gold_hit@5_count"] == 1
    assert payload["strategies"]["sparse"]["gold_hit@5_count"] == 0
    assert payload["strategies"]["hybrid"]["gold_hit@5_count"] == 0
    assert payload["recovered"]["dense_recovers"] == 1
    assert payload["recovered"]["sparse_recovers"] == 0
    assert payload["answer_cell_warranted"] is True
    assert payload["cells"][0]["dense"]["candidate_keys"][0] == "gold"
    assert "gold" not in payload["cells"][0]["hybrid"]["candidate_keys"]


def test_signals_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert DIRECT.is_file()
    assert C8.is_file()
    before_v1 = TABULAR_V1.read_bytes()
    before_direct = DIRECT.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "headline": {"answer_cell_warranted": False},
        "strategies": {},
        "confidentiality": {},
        "recovered": {},
        "answer_cell_warranted": False,
        "hybrid_matches_frozen": 0,
        "cells": [],
        "gold_positive_cells": 0,
    }
    target = tmp_path / "phase2-tabular-signals-v1.json"
    write_tabular_signals_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_signals_baseline(payload, target)
    frozen = freeze_tabular_signals(payload)
    assert frozen["id"] == "phase2-tabular-signals-v1"
    assert frozen["no_answer_cell"] is True
    assert frozen["no_new_algorithm"] is True
    assert frozen["does_not_replace_tabular_direct"] is True
    assert frozen["retrieval_baseline"] == "hybrid"
    assert TABULAR_V1.read_bytes() == before_v1
    assert DIRECT.read_bytes() == before_direct
    assert C8.read_bytes() == before_c8
    assert TABULAR_SIGNALS_PATH != TABULAR_V1
    assert RETRIEVAL_CONCLUSIONS["tabular_performance_reference"] == "jev_d"
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_right_five"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_not_more_model_steps"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_signals"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_hit5_beat_hybrid"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_sparse_did_not_beat_hybrid"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_dense_recovered_confidentiality"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_answer_cell_warranted_for_dense"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_assume_recall_is_cell_quality"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_hybrid"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_dense_answer_cell"] is False
    assert RETRIEVAL_CONCLUSIONS["do_not_widen_tabular_k"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_start_new_embedding"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_b"] is True


def test_frozen_tabular_signals_dense_beat_hybrid() -> None:
    frozen = load_tabular_signals_baseline()
    assert frozen["id"] == "phase2-tabular-signals-v1"
    assert frozen["no_answer_cell"] is True
    assert frozen["answer_cell_warranted"] is True
    assert frozen["hybrid_matches_frozen"] == 100
    assert frozen["headline"]["gold_hit@5_count"] == {
        "dense": 27,
        "sparse": 18,
        "hybrid": 20,
    }
    assert frozen["headline"]["gold_hit@10_count"] == {
        "dense": 27,
        "sparse": 19,
        "hybrid": 25,
    }
    assert frozen["headline"]["confidentiality_hit@5_count"] == {
        "dense": 8,
        "sparse": 0,
        "hybrid": 1,
    }
    assert frozen["headline"]["dense_recovers_hybrid_miss"] == 7
    assert frozen["headline"]["sparse_recovers_hybrid_miss"] == 0
    assert frozen["recovered"]["hybrid_misses_are_confidentiality"] is True
    assert frozen["does_not_replace_tabular_direct"] is True
    assert frozen["retrieval_baseline"] == "hybrid"
