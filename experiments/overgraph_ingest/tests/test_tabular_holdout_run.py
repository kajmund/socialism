from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_holdout_gold_baseline,
    load_tabular_holdout_run_baseline,
)
from overgraph_ingest.tabular.cells import VARIANT_D, VARIANT_E, VARIANT_K
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND
from overgraph_ingest.tabular.evaluate import CORRECT_NOT_FOUND, TRUE_ANSWER
from overgraph_ingest.tabular.holdout_run import (
    HOLD_OUT_RUN_PATH,
    HOLD_OUT_SPECS,
    decide_holdout,
    run_tabular_holdout,
    write_holdout_run_baseline,
    write_holdout_run_table,
)
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_eval import polarity_split, score_user_cell
from overgraph_ingest.tabular.user_gold import (
    CELL_MAY_HAVE_MULTIPLE_ANSWERS,
    SILENT,
    YES,
    GoldSpan,
    UserCellGold,
)
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
DIRECT = ROOT / "baselines" / "phase2-tabular-direct-v1.json"
GOLD = ROOT / "baselines" / "phase2-tabular-holdout-gold-v1.json"
PATH = "Avtal_holdout_script.docx"
SPAN = "Avtalet förlängs automatiskt med tolv månader."


class HoldoutJev:
    def __init__(self) -> None:
        self.calls = 0
        self.kinds: list[str] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        kind = next(iter(questions))
        self.kinds.append(kind)
        if "status" not in questions:
            raise AssertionError(f"holdout must not classify: {kind}")
        question = str(state.get("question") or "")
        if "automatiskt" not in question:
            return _jev(
                {
                    "status": {"choice": NOT_FOUND},
                    "source": {"choice": "none"},
                    "excerpt": {"choice": "none"},
                }
            )
        excerpt = next(
            (
                key
                for key, text in questions["excerpt"]["criteria"].items()
                if key != "none" and "förlängs automatiskt" in text
            ),
            None,
        )
        if excerpt is None:
            return _jev(
                {
                    "status": {"choice": NOT_FOUND},
                    "source": {"choice": "none"},
                    "excerpt": {"choice": "none"},
                }
            )
        source = next(
            key
            for key, text in questions["source"]["criteria"].items()
            if key != "none" and "förlängs automatiskt" in text
        )
        return _jev(
            {
                "status": {"choice": ANSWERED},
                "source": {"choice": source},
                "excerpt": {"choice": excerpt},
            }
        )


def _jev(answers: dict[str, object]) -> JevResult:
    return JevResult(
        answers=answers,
        model="jev-latest",
        latency_ms=1.0,
        usage=JevUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
        raw={"answers": answers},
    )


def _units() -> list:
    rows = [
        _unit(
            f"noise-{index}",
            PATH,
            "Ingen sekretess.",
            sequence=index,
            dense=[0.0, 1.0],
            sparse=[(2, 1.0)],
        )
        for index in range(1, 10)
    ]
    rows.append(
        _unit(
            "gold",
            PATH,
            SPAN,
            sequence=10,
            dense=[1.0, 0.0],
            sparse=[(1, 1.0)],
        )
    )
    return rows


def _golds() -> dict[tuple[str, str], UserCellGold]:
    return {
        (PATH, "auto-renewal"): UserCellGold(
            PATH,
            "auto-renewal",
            YES,
            (GoldSpan("förlängs automatiskt"),),
        ),
        (PATH, "notice-period"): UserCellGold(PATH, "notice-period", SILENT, ()),
    }


def _queries() -> dict[str, tuple[list[float], list[tuple[int, float]]]]:
    encoded = ([1.0, 0.0], [(1, 1.0)])
    return {"auto-renewal": encoded, "notice-period": encoded}


def test_holdout_run_is_one_answer_cell_per_variant() -> None:
    jev = HoldoutJev()
    payload = run_tabular_holdout(
        units=_units(),
        structures={},
        queries=_queries(),
        jev=jev,
        documents=(PATH,),
        question_ids=("auto-renewal", "notice-period"),
        golds=_golds(),
    )
    assert payload["one_jev_call"] is True
    assert payload["no_classify"] is True
    assert payload["does_not_change_ingest"] is True
    assert payload["no_structural_preprocess"] is True
    assert payload["default_remains_d"] is True
    assert payload["e_is_next_candidate"] is True
    assert payload["decision"]["do_not_switch_default"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
    assert HOLD_OUT_SPECS == (
        (VARIANT_D, "hybrid", 5),
        (VARIANT_E, "dense", 5),
        (VARIANT_K, "hybrid", 10),
    )
    assert jev.calls == 6
    assert jev.kinds == ["status"] * 6
    assert payload["jev_calls"] == 6
    assert len(payload["cells"]) == 6
    by_variant = {name: [] for name, _, _ in HOLD_OUT_SPECS}
    for cell in payload["cells"]:
        by_variant[str(cell["variant"])].append(cell)
    assert by_variant[VARIANT_D][0]["retrieval"]["strategy"] == "hybrid"
    assert by_variant[VARIANT_D][0]["retrieval"]["k"] == 5
    assert by_variant[VARIANT_E][0]["retrieval"]["strategy"] == "dense"
    assert by_variant[VARIANT_K][0]["retrieval"]["k"] == 10
    assert len(by_variant[VARIANT_K][0]["retrieval"]["candidate_keys"]) == 10
    for name in by_variant:
        auto = next(row for row in payload["scored"][name] if row["question_id"] == "auto-renewal")
        silent = next(row for row in payload["scored"][name] if row["question_id"] == "notice-period")
        assert auto["outcome"] == TRUE_ANSWER
        assert silent["outcome"] == CORRECT_NOT_FOUND
        split = payload["variants"][name]["summary"]["polarity"]
        assert split["positive_cells"] == 1
        assert split["negative_cells"] == 1
        assert split["positive_correct"] == 1
        assert split["negative_stayed_negative"] == 1
        assert split["negative_false_answer"] == 0


def test_polarity_split_counts_positive_and_silent() -> None:
    golds = _golds()
    rows = [
        score_user_cell(
            {
                "document_id": "a",
                "status": ANSWERED,
                "answer": SPAN,
                "sources": [{"excerpt": SPAN}],
                "variant": VARIANT_D,
            },
            golds[(PATH, "auto-renewal")],
        ),
        score_user_cell(
            {
                "document_id": "a",
                "status": ANSWERED,
                "answer": "påhittad tystnadsplikt",
                "sources": [{"excerpt": "påhittad tystnadsplikt"}],
                "variant": VARIANT_D,
            },
            golds[(PATH, "notice-period")],
        ),
    ]
    split = polarity_split(rows)
    assert split["positive_correct"] == 1
    assert split["negative_stayed_negative"] == 0
    assert split["negative_false_answer"] == 1


def test_decide_holdout_does_not_switch_default() -> None:
    summaries = {
        VARIANT_D: {
            "polarity": {
                "positive_correct_rate": 0.7,
                "negative_false_answer": 4,
            }
        },
        VARIANT_E: {
            "polarity": {
                "positive_correct_rate": 0.8,
                "negative_false_answer": 4,
            }
        },
        VARIANT_K: {
            "polarity": {
                "positive_correct_rate": 0.8,
                "negative_false_answer": 5,
            }
        },
    }
    decision = decide_holdout(summaries)
    assert decision["e_improves_positive_without_extra_silent_false_answers"] is True
    assert decision["k_beats_both_on_positive"] is False
    assert decision["do_not_switch_default"] is True
    assert decision["default_remains_d"] is True


def test_holdout_run_baseline_is_write_once(tmp_path: Path) -> None:
    before_gold = GOLD.read_bytes()
    before_direct = DIRECT.read_bytes()
    before_c8 = C8.read_bytes()
    payload = run_tabular_holdout(
        units=_units(),
        structures={},
        queries=_queries(),
        jev=HoldoutJev(),
        documents=(PATH,),
        question_ids=("auto-renewal", "notice-period"),
        golds=_golds(),
    )
    table = write_holdout_run_table(payload, tmp_path)
    assert "Positive correct" in table.read_text(encoding="utf-8")
    target = tmp_path / "phase2-tabular-holdout-run-v1.json"
    write_holdout_run_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_holdout_run_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_holdout_run_baseline(payload, C8)
    with pytest.raises(FileExistsError):
        write_holdout_run_baseline(payload, GOLD)
    assert GOLD.read_bytes() == before_gold
    assert DIRECT.read_bytes() == before_direct
    assert C8.read_bytes() == before_c8
    assert HOLD_OUT_RUN_PATH != GOLD
    assert CELL_MAY_HAVE_MULTIPLE_ANSWERS is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS


def test_frozen_holdout_run_keeps_default_d() -> None:
    frozen = load_tabular_holdout_run_baseline()
    gold = load_tabular_holdout_gold_baseline()
    assert frozen["id"] == "phase2-tabular-holdout-run-v1"
    assert frozen["default_remains_d"] is True
    assert frozen["e_is_next_candidate"] is True
    assert frozen["one_jev_call"] is True
    assert frozen["no_structural_preprocess"] is True
    assert frozen["does_not_change_ingest"] is True
    assert frozen["jev_calls"] == 300
    assert gold["models_not_run"] is True
    assert frozen["headline"]["D"]["full_success_rate"] == 0.79
    assert frozen["headline"]["E"]["full_success_rate"] == 0.89
    assert frozen["headline"]["K"]["full_success_rate"] == 0.87
    assert frozen["headline"]["D"]["polarity"]["positive_correct"] == 27
    assert frozen["headline"]["E"]["polarity"]["positive_correct"] == 39
    assert frozen["headline"]["K"]["polarity"]["positive_correct"] == 35
    assert frozen["headline"]["D"]["polarity"]["negative_stayed_negative"] == 52
    assert frozen["headline"]["E"]["polarity"]["negative_stayed_negative"] == 50
    assert frozen["headline"]["K"]["polarity"]["negative_stayed_negative"] == 52
    assert frozen["headline"]["D"]["polarity"]["negative_false_answer"] == 5
    assert frozen["headline"]["E"]["polarity"]["negative_false_answer"] == 6
    assert frozen["headline"]["K"]["polarity"]["negative_false_answer"] == 4
    assert frozen["decision"]["do_not_switch_default"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_holdout_run"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_holdout_models_not_run"] is False
    assert RETRIEVAL_CONCLUSIONS["tabular_default_remains_d"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_e_is_next_candidate"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_holdout_k_did_not_beat_e"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_holdout_do_not_pay_k10"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_default_hybrid"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
