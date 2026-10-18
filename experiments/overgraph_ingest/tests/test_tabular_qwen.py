from __future__ import annotations

import json
from pathlib import Path

import pytest

from overgraph_ingest.cerebras.client import CerebrasReply
from overgraph_ingest.cerebras.qwen import QWEN_MODEL, QWEN_REASONING_EFFORT
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_qwen_baseline,
    load_tabular_review_baseline,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.contract import ANSWERED
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.qwen import (
    TABULAR_QWEN_PATH,
    VARIANT_Q,
    freeze_tabular_qwen,
    frozen_c_cells,
    run_tabular_qwen,
    write_tabular_qwen_baseline,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "retrieval_gold"
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"


class FakeQwen:
    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        payload = json.loads(messages[1]["content"])
        unit = payload["units"][0]
        return CerebrasReply(
            text=json.dumps(
                {
                    "status": ANSWERED,
                    "answer": "Ja, avtalet förlängs automatiskt.",
                    "source_unit_id": unit["id"],
                    "excerpt": "förlängs automatiskt",
                },
                ensure_ascii=False,
            ),
            ttft_seconds=0.01,
            completion_seconds=0.02,
            prompt_tokens=20,
            completion_tokens=8,
        )


def _unit() -> StoredUnit:
    text = "Avtalet förlängs automatiskt med tolv månader."
    return StoredUnit(
        1,
        "gold",
        "doc-a",
        "Avtal_17_Hyresavtal_lokal.docx",
        text,
        [1.0, 0.0],
        [(1, 1.0)],
        "s1",
        1,
        0,
        len(text),
    )


def _frozen_cell() -> dict[str, object]:
    return {
        "document_id": "Avtal_17_Hyresavtal_lokal",
        "relative_path": "Avtal_17_Hyresavtal_lokal.docx",
        "question_id": "auto-renewal",
        "question": USER_QUESTIONS["auto-renewal"],
        "variant": "C",
        "status": ANSWERED,
        "retrieval": {
            "k": 5,
            "candidate_keys": ["gold"],
            "recall@3": 1.0,
            "recall@5": 1.0,
            "recall@10": 1.0,
        },
    }


def test_qwen_uses_reasoning_low() -> None:
    assert QWEN_REASONING_EFFORT == "low"
    assert QWEN_MODEL == "qwen-3.8-27b"


def test_frozen_tabular_v1_has_exactly_100_c_cells() -> None:
    cells = frozen_c_cells(load_tabular_review_baseline())
    assert len(cells) == 100
    keys = {(row["relative_path"], row["question_id"]) for row in cells}
    assert len(keys) == 100


def test_qwen_replays_frozen_candidate_keys() -> None:
    unit = _unit()
    payload = run_tabular_qwen(
        gold_dir=GOLD_DIR,
        frozen={"cells": [_frozen_cell()], "scored": []},
        units=[unit],
        structures={},
        client=FakeQwen(),
        expected_cells=1,
    )
    assert payload["model"] == QWEN_MODEL
    assert payload["reasoning_effort"] == "low"
    assert payload["same_candidate_keys"] is True
    assert payload["no_new_retrieval"] is True
    assert payload["no_navigation"] is True
    assert payload["does_not_replace_tabular_v1"] is True
    assert payload["cells"][0]["variant"] == VARIANT_Q
    assert payload["cells"][0]["retrieval"]["candidate_keys"] == ["gold"]
    assert payload["cells"][0]["status"] == ANSWERED
    assert payload["cells"][0]["source_unit_ids"] == ["gold"]


def test_qwen_freeze_does_not_overwrite_tabular_v1(tmp_path: Path) -> None:
    assert TABULAR_V1.is_file()
    assert C8.is_file()
    before = TABULAR_V1.read_bytes()
    payload = {
        "headline": {"qwen_cell_accuracy": 0.0},
        "versus": {},
        "qwen": {},
        "cost": {},
        "errors": {},
        "cells": [],
        "scored": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-qwen-v1.json"
    write_tabular_qwen_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_qwen_baseline(payload, target)
    frozen = freeze_tabular_qwen(payload)
    assert frozen["does_not_replace_tabular_v1"] is True
    assert frozen["navigation_not_changed"] is True
    assert frozen["reasoning_effort"] == "low"
    assert TABULAR_V1.read_bytes() == before
    assert TABULAR_QWEN_PATH != TABULAR_V1
    assert RETRIEVAL_CONCLUSIONS["tabular_qwen"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_qwen_reasoning"] == "low"
    assert RETRIEVAL_CONCLUSIONS["tabular_qwen_did_not_beat_jev"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_qwen_beat_cerebras"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_qwen_navigation_not_changed"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_second_run_100_not_started"] is True


def test_frozen_tabular_qwen_is_same_100_cells() -> None:
    frozen = load_tabular_qwen_baseline()
    assert frozen["id"] == "phase2-tabular-qwen-v1"
    assert frozen["reasoning_effort"] == "low"
    assert frozen["same_100_cells"] is True
    assert frozen["no_new_retrieval"] is True
    assert frozen["does_not_replace_tabular_v1"] is True
    assert frozen["navigation_not_changed"] is True
    assert frozen["headline"]["cell_accuracy"]["Q"] == 0.78
    assert frozen["headline"]["cell_accuracy"]["B"] == 0.78
    assert frozen["headline"]["cell_accuracy"]["C"] == 0.71
    assert frozen["headline"]["answer_accuracy"]["Q"] == 0.82
    assert len(frozen["cells"]) == 100
    keys = {(row["relative_path"], row["question_id"]) for row in frozen["cells"]}
    assert len(keys) == 100
    assert {row["variant"] for row in frozen["cells"]} == {VARIANT_Q}
