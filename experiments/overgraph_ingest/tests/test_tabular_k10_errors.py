from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.jev.candidates import context_from_units
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_k10_errors_baseline,
)
from overgraph_ingest.tabular.cells import VARIANT_B, run_cell
from overgraph_ingest.tabular.contract import ANSWERED
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.k10_errors import (
    GOLD_NARROW,
    TABULAR_K10_ERRORS_PATH,
    WRONG_RELATION,
    b_classify_gates_answer,
    freeze_tabular_k10_errors,
    run_tabular_k10_errors,
    write_tabular_k10_errors_baseline,
)
from overgraph_ingest.tabular.search import DEFAULT_K
from tests.test_tabular_review import ScriptedJev, _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
K10 = ROOT / "baselines" / "phase2-tabular-k10-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"


def test_b_classify_does_not_gate_answered() -> None:
    assert b_classify_gates_answer() is False
    assert DEFAULT_K == 5
    path = "Avtal_08_Konkurrensforbudsavtal.docx"
    unit = _unit("vite", path, "Vite utgår vid brott mot förbudet.")
    result = run_cell(
        variant=VARIANT_B,
        relative_path=path,
        question_id="liability-cap",
        user_question=USER_QUESTIONS["liability-cap"],
        classify_question="Innehåller texten en ansvarsbegränsning?",
        units=[unit],
        context=context_from_units([unit], {}),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys=set(),
        jev=ScriptedJev(),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
    )
    assert result.status == ANSWERED
    assert result.source_unit_ids == ["vite"]


def test_k10_errors_are_new_tail_not_top5() -> None:
    payload = run_tabular_k10_errors()
    assert payload["no_new_model"] is True
    assert payload["classify_gates_b_answer"] is False
    assert payload["answer_sees"] == "all_examined_units"
    assert payload["headline"]["new_gold_negative_false_answers"] == 9
    assert payload["headline"]["cited_new_tail"] == 9
    assert payload["headline"]["cited_b_top5"] == 0
    assert payload["headline"]["same_top5"] is True
    assert payload["headline"]["gold_narrow"] == 4
    assert payload["headline"]["wrong_relation"] == 5
    ranks = {row["cited_rank"] for row in payload["rows"]}
    assert ranks <= {6, 7, 8, 9, 10}
    assert {row["label"] for row in payload["rows"]} == {GOLD_NARROW, WRONG_RELATION}
    assert RETRIEVAL_CONCLUSIONS["tabular_b_classify_does_not_gate_answer"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_k10_false_positives_are_new_tail"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_build_tabular_controller"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_widen_tabular_k"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_start_new_embedding"] is True


def test_k10_errors_freeze_does_not_overwrite_prior_baselines(tmp_path: Path) -> None:
    before_v1 = TABULAR_V1.read_bytes()
    before_k10 = K10.read_bytes()
    before_c8 = C8.read_bytes()
    payload = run_tabular_k10_errors()
    target = tmp_path / "phase2-tabular-k10-errors-v1.json"
    write_tabular_k10_errors_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_k10_errors_baseline(payload, target)
    frozen = freeze_tabular_k10_errors(payload)
    assert frozen["classify_gates_b_answer"] is False
    assert frozen["does_not_replace_tabular_v1"] is True
    assert TABULAR_V1.read_bytes() == before_v1
    assert K10.read_bytes() == before_k10
    assert C8.read_bytes() == before_c8
    assert TABULAR_K10_ERRORS_PATH != TABULAR_V1


def test_frozen_k10_errors_lists_nine_tail_citations() -> None:
    frozen = load_tabular_k10_errors_baseline()
    assert frozen["id"] == "phase2-tabular-k10-errors-v1"
    assert frozen["headline"]["cited_new_tail"] == 9
    assert frozen["headline"]["cited_b_top5"] == 0
    assert len(frozen["rows"]) == 9
